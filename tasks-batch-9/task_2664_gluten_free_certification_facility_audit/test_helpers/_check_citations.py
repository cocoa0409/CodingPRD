"""Developer utility: confirm every PRD: "..." citation in the suite is verbatim
and that every test carries exactly one Design: tag.

Run as:  python3 test_helpers/_check_citations.py
"""

import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    prd = normalize(open(os.path.join(ROOT, "workspace", "PRD.md")).read())
    bad = 0
    tests = 0
    for path in sorted(glob.glob(os.path.join(ROOT, "test_suite", "test_*.py"))):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node) or ""
            if node.name.startswith("test_"):
                tests += 1
                tags = re.findall(r"^Design: .+$", doc, flags=re.M)
                if len(tags) != 1:
                    print(f"TAG {len(tags)} {os.path.basename(path)}::{node.name}")
                    bad += 1
                elif not doc.rstrip().endswith(tags[0]):
                    print(f"TAG-NOT-LAST {os.path.basename(path)}::{node.name}")
                    bad += 1
            for quote in re.findall(r'PRD: "(.*?)"\n', doc + "\n", flags=re.S):
                if normalize(quote) not in prd:
                    print(f"CITE {os.path.basename(path)}::{node.name}: {normalize(quote)[:90]}")
                    bad += 1
    print(f"tests={tests} problems={bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
