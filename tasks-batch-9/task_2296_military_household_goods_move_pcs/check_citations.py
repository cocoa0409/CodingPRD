"""Verify every docstring quotation appears verbatim in PRD.md and every test carries one tag."""

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
PRD = (ROOT / "workspace" / "PRD.md").read_text()
PRD_NORM = re.sub(r"\s+", " ", PRD)


def quotations(doc):
    """Pull out every double-quoted block from a docstring."""
    body = doc
    out = []
    for match in re.finditer(r'"([^"]{40,})"', body, re.S):
        out.append(re.sub(r"\s+", " ", match.group(1)).strip())
    return out


def main(paths):
    bad = 0
    total = 0
    for path in paths:
        tree = ast.parse(pathlib.Path(path).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            total += 1
            doc = ast.get_docstring(node, clean=False) or ""
            lines = [ln.strip() for ln in doc.strip().splitlines() if ln.strip()]
            tags = [ln for ln in lines if ln.startswith("Design:")]
            if len(tags) != 1 or lines[-1] != tags[0]:
                print(f"TAG {path}:{node.lineno} {node.name}: {tags}")
                bad += 1
            for quote in quotations(doc):
                if quote not in PRD_NORM:
                    print(f"QUOTE {path}:{node.lineno} {node.name}:\n  {quote}\n")
                    bad += 1
    print(f"checked {total} tests, {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
