"""Stage 2 lint: audit Design-tag coverage in test_suite against the two design yamls.

AST-based: extracts every test function's docstring, counts its `Design:` lines,
verifies each tag resolves to a real design-index instance, and checks coverage
floors (Difficulty >= 2 tests/instance, Corner >= 1 test/non-stub instance).
"""
import ast
import sys
from pathlib import Path

import yaml

TASK = Path(__file__).parent
SUITE = TASK / "test_suite"


def load_instances():
    diff = yaml.safe_load((TASK / "SCAFFOLD_DIFFICULTY_DESIGN.yaml").read_text())
    corner = yaml.safe_load((TASK / "SCAFFOLD_CORNER_DESIGN.yaml").read_text())
    difficulty = {}
    for rule in diff["scaffold_difficulty_design"]:
        for inst in rule["instances"]:
            difficulty[f"Difficulty/{rule['rule_id']}/{inst['name']}"] = inst
    corners = {}
    stubs = {}
    for section in corner["scaffold_corner_design"]:
        for inst in section["instances"]:
            key = f"Corner/{section['section']}/{inst['name']}"
            if "excluded_because" in inst:
                stubs[key] = inst
            else:
                corners[key] = inst
    return difficulty, corners, stubs


def collect_tags():
    """Return (tags: tag -> [(file, test)], problems: [str])."""
    tags = {}
    problems = []
    for path in sorted(SUITE.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            doc = ast.get_docstring(node)
            if doc is None:
                problems.append(f"NO-DOCSTRING {path.name}::{node.name}")
                continue
            lines = [ln.strip() for ln in doc.splitlines()
                     if ln.strip().startswith("Design:")]
            if len(lines) != 1:
                problems.append(
                    f"TAG-COUNT {path.name}::{node.name}: {len(lines)} Design lines")
                continue
            tag = lines[0][len("Design:"):].strip()
            # Tag must be the LAST line of the docstring.
            if doc.strip().splitlines()[-1].strip() != lines[0]:
                problems.append(
                    f"TAG-NOT-LAST {path.name}::{node.name}")
            tags.setdefault(tag, []).append((path.name, node.name))
    return tags, problems


def main():
    difficulty, corners, stubs = load_instances()
    tags, problems = collect_tags()

    ok = True
    for p in problems:
        print(p)
        ok = False
    for tag, uses in sorted(tags.items()):
        if tag not in difficulty and tag not in corners:
            print(f"BAD-TAG {tag} used by {uses}")
            ok = False
    for tag in sorted(difficulty):
        n = len(tags.get(tag, []))
        if n < 2:
            print(f"MISSING-DIFFICULTY {tag}: {n} tests (need >= 2)")
            ok = False
    for tag in sorted(corners):
        n = len(tags.get(tag, []))
        if n < 1:
            print(f"MISSING-CORNER {tag}: {n} tests (need >= 1)")
            ok = False
    for tag, inst in sorted(stubs.items()):
        if tag in tags:
            print(f"STUB-TRANSLATED {tag} should not have tests")
            ok = False
        ref = inst["excluded_because"]["difficulty_instance"]
        if not any(d.endswith(f"/{ref}") for d in difficulty):
            print(f"STUB-BROKEN-REF {tag} -> {ref}")
            ok = False

    total_a = sum(len(v) for k, v in tags.items() if k.startswith("Difficulty/"))
    total_b = sum(len(v) for k, v in tags.items() if k.startswith("Corner/"))
    n_tests = sum(len(v) for v in tags.values())
    print(f"\nQueue A (Difficulty): {total_a} tests over {len(difficulty)} instances")
    print(f"Queue B (Corner):     {total_b} tests over {len(corners)} non-stub instances "
          f"({len(stubs)} stubs excluded)")
    print(f"Total tagged tests:   {n_tests}")
    print("VERDICT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
