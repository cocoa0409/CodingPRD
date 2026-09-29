"""Verify every Design tag resolves and count coverage per design instance."""

import ast
import collections
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).parent


def load_design():
    tags = {}
    difficulty = yaml.safe_load((ROOT / "SCAFFOLD_DIFFICULTY_DESIGN.yaml").read_text())
    for rule in difficulty["scaffold_difficulty_design"]:
        for inst in rule.get("instances", []):
            key = f"Difficulty/{rule['rule_id']}/{inst['name']}"
            tags[key] = bool(inst.get("test_recipe"))
    corner = yaml.safe_load((ROOT / "SCAFFOLD_CORNER_DESIGN.yaml").read_text())
    for section in corner["scaffold_corner_design"]:
        for inst in section.get("instances", []):
            key = f"Corner/{section['section']}/{inst['name']}"
            tags[key] = bool(inst.get("test_recipe"))
    return tags


def main():
    known = load_design()
    counts = collections.Counter()
    problems = []
    total = 0
    for path in sorted((ROOT / "test_suite").glob("test_*.py")):
        tree = ast.parse(path.read_text())
        per_file = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
                continue
            per_file += 1
            total += 1
            doc = ast.get_docstring(node) or ""
            found = re.findall(r"^\s*Design: (\S+)\s*$", doc, re.M)
            if len(found) != 1:
                problems.append(f"{path.name}::{node.name}: {len(found)} Design lines")
                continue
            tag = found[0]
            if tag not in known:
                problems.append(f"{path.name}::{node.name}: unknown tag {tag}")
            elif not known[tag]:
                problems.append(f"{path.name}::{node.name}: tag is a stub {tag}")
            counts[tag] += 1
        if per_file < 5:
            problems.append(f"{path.name}: only {per_file} tests")

    for key, non_stub in sorted(known.items()):
        if not non_stub:
            continue
        floor = 2 if key.startswith("Difficulty/") else 1
        if counts[key] < floor:
            problems.append(f"UNCOVERED ({counts[key]}/{floor}): {key}")

    print(f"{total} tests, {len(counts)} instances tagged")
    for problem in problems:
        print("  " + problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
