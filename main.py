import argparse
import os
import re
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from dotenv import load_dotenv
from gyazo import Api


def extract_deco(t: str) -> str:
    patterns = [
        r"\*\*(.+?)\*\*",  # **bold**
    ]
    for pattern in patterns:
        t = re.sub(pattern, r"\1", t)
    return t


def mask_ref(t: str) -> Tuple[str, Dict[str, str]]:
    ref_mask_dict = {}
    match = re.search(r"#+\s+References?", t, re.IGNORECASE)
    if not match:
        return t, ref_mask_dict

    # find the range of the section
    start = match.end()
    next_sec_match = re.search(r"#+\s+\w+", t[start:])
    if next_sec_match:
        end = start + next_sec_match.start()
    else:
        end = len(t)

    # mask the section
    masked = t[:start] + "#REF#" + t[end:]
    ref_mask_dict["#REF#"] = t[start:end]
    return masked, ref_mask_dict


def mask_math(t: str) -> Tuple[str, Dict[str, str]]:
    math_mask_dict = {}
    pattern = re.compile(r"\${1,2}(.*?)\${1,2}", re.DOTALL)
    newline = re.compile(r"\n")
    counter = 1

    def repl(match):
        nonlocal counter
        mask = f"EQ{counter:03d}"
        math = newline.sub(r" ", match.group(1))
        math_mask_dict[mask] = f"[$ {math} ]"
        counter += 1
        return mask

    masked = pattern.sub(repl, t)
    return masked, math_mask_dict


def unmask_ref(t: str, ref_mask_dict: Dict[str, str]) -> str:
    for mask, ref in ref_mask_dict.items():
        t = t.replace(mask, ref)
    return t


def escape_brackets(t: str) -> str:
    pattern = re.compile(r"\[(.*?)\]")
    t = pattern.sub(r"`[\1]`", t)
    return t


def unmask_math(t: str, math_mask_dict: Dict[str, str]) -> str:
    for mask, math in math_mask_dict.items():
        # math = re.sub(r"\\", r"\\\\", math)
        # t = re.sub(mask, math, t, flags=re.IGNORECASE)
        t = t.replace(mask, math)
    return t


def replace_headings(t: str) -> str:
    pattern = re.compile(r"^[\d\.]*(#+)\s+(.+?)\n")

    def repl(match):
        level_md = len(match.group(1))
        level_scb = max(1, 4 - level_md)
        return f"[{'*' * level_scb} {match.group(2)}]"

    t = pattern.sub(repl, t)
    return t


def replace_images(t: str) -> str:
    pattern = re.compile(r"!`\[(.*?)\]`\((.*?)\)")
    client = Api(access_token=os.getenv("GYAZO_ACCESS_TOKEN"))

    def repl(match):
        src = match.group(2)
        # download image
        response = requests.get(src)
        if response.status_code != 200:
            print(f"Error: image not found {src}")
            exit(1)
        # save image
        img = BytesIO(response.content)
        # upload to gyazo
        url = (
            client.upload_image(img)
            .url.replace("i.gyazo.com", "gyazo.com")
            .replace(".png", "")
            .replace(".jpg", "")
        )
        return f"[{url}]"

    t = pattern.sub(repl, t)
    return t


def translate(t: str, source: str, target: str) -> str:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    payload = {
        "auth_key": os.getenv("DEEPL_API_KEY"),
        "text": t,
        "source_lang": source,
        "target_lang": target,
    }
    response = requests.post(
        "https://api-free.deepl.com/v2/translate",
        headers=headers,
        data=payload,
    )
    if response.status_code != 200:
        print(response.json())
        print(f"Error: DeepL API responsed {response.status_code}")
        exit(1)

    return response.json()["translations"][0]["text"]


def main():
    parser = argparse.ArgumentParser(
        description="Translate and convert TeX / Mathpix Markdown"
    )
    parser.add_argument("path", type=str, help="path to input file")
    parser.add_argument("--no-copy", action="store_true", help="copy to clipboard")
    parser.add_argument("--source", type=str, default="EN", help="source language")
    parser.add_argument("--target", type=str, default="JA", help="target language")
    parser.add_argument("--debug", action="store_true", help="debug mode")
    args = parser.parse_args()

    load_dotenv()

    path = Path(args.path)
    if not path.is_absolute():
        path = Path(os.getenv("INPUT_DIR")) / path

    with open(path, "r", encoding="utf-8") as f:
        t = f.read()

    print("preprocessing...")
    t = extract_deco(t)
    t, ref_mask_dict = mask_ref(t)
    t, math_mask_dict = mask_math(t)
    if args.debug:
        with open("log/masked.txt", "w", encoding="utf-8") as f:
            f.write(t)
        with open("log/math_mask.txt", "w", encoding="utf-8") as f:
            for mask, math in math_mask_dict.items():
                f.write(f"{mask}: {math}\n")
        with open("log/ref_mask.txt", "w", encoding="utf-8") as f:
            for mask, ref in ref_mask_dict.items():
                f.write(f"{mask}: {ref}\n")

    print("translating...")
    t = translate(t, args.source, args.target)
    if args.debug:
        with open("log/translated.txt", "w", encoding="utf-8") as f:
            f.write(t)

    print("postprocessing...")
    t = unmask_ref(t, ref_mask_dict)
    t = escape_brackets(t)
    t = unmask_math(t, math_mask_dict)
    t = replace_headings(t)
    t = replace_images(t)
    if args.debug:
        with open("log/unmasked.txt", "w", encoding="utf-8") as f:
            f.write(t)

    if not args.no_copy:
        # copy to clipboard
        subprocess.run("clip.exe", input=t.encode("utf-16"), check=True)
        print("Converted text has been copied to clipboard.")


if __name__ == "__main__":
    main()
