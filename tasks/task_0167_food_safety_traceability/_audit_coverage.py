"""Dev-only: cross-check Design tags against the two design indices.
- Every difficulty instance covered by >= 2 tests.
- Every non-stub corner instance covered by >= 1 test.
- Every tag resolves to a real instance.
Deleted before completion."""
import re, ast, pathlib, yaml, sys, collections

ROOT = pathlib.Path(__file__).parent

diff = yaml.safe_load((ROOT / "SCAFFOLD_DIFFICULTY_DESIGN.yaml").read_text())["scaffold_difficulty_design"]
corner = yaml.safe_load((ROOT / "SCAFFOLD_CORNER_DESIGN.yaml").read_text())["scaffold_corner_design"]

# Build expected sets.
diff_instances = {}   # rule_id -> set(names)
for rule in diff:
    diff_instances[rule["rule_id"]] = {inst["name"] for inst in rule["instances"]}

corner_nonstub = collections.defaultdict(set)   # section -> set(names)
corner_stub = collections.defaultdict(set)
for sec in corner:
    s = sec["section"]
    for inst in sec["instances"]:
        if "excluded_because" in inst:
            corner_stub[s].add(inst["name"])
        else:
            corner_nonstub[s].add(inst["name"])

# Collect tags from tests.
diff_tags = collections.Counter()   # (rule_id, name)
corner_tags = collections.Counter()  # (section, name)
for f in sorted((ROOT / "test_suite").glob("test_*.py")):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            doc = ast.get_docstring(node) or ""
            for kind, rest in re.findall(r"Design: (Difficulty|Corner)/(\S+)", doc):
                parts = rest.split("/")
                key = (parts[0], parts[1])
                (diff_tags if kind == "Difficulty" else corner_tags)[key] += 1

problems = []

# Difficulty: >= 2 each, tag resolves.
for (rule_id, name), cnt in diff_tags.items():
    if rule_id not in diff_instances or name not in diff_instances[rule_id]:
        problems.append(f"Difficulty tag does not resolve: {rule_id}/{name}")
for rule_id, names in diff_instances.items():
    for name in names:
        cnt = diff_tags.get((rule_id, name), 0)
        if cnt < 2:
            problems.append(f"Difficulty under-covered (<2): {rule_id}/{name} has {cnt}")

# Corner: >= 1 each non-stub, tag resolves, no stub translated.
for (section, name), cnt in corner_tags.items():
    in_nonstub = name in corner_nonstub.get(section, set())
    in_stub = name in corner_stub.get(section, set())
    if in_stub:
        problems.append(f"Corner STUB was translated (forbidden): {section}/{name}")
    elif not in_nonstub:
        problems.append(f"Corner tag does not resolve to non-stub: {section}/{name}")
for section, names in corner_nonstub.items():
    for name in names:
        if corner_tags.get((section, name), 0) < 1:
            problems.append(f"Corner under-covered (<1): {section}/{name}")

print("Difficulty instances:", sum(len(v) for v in diff_instances.values()),
      "| tags:", sum(diff_tags.values()))
print("Corner non-stub instances:", sum(len(v) for v in corner_nonstub.values()),
      "| stubs:", sum(len(v) for v in corner_stub.values()),
      "| tags:", sum(corner_tags.values()))

# Verify each stub's difficulty cross-reference resolves.
for sec in corner:
    for inst in sec["instances"]:
        eb = inst.get("excluded_because")
        if eb:
            ref = eb["difficulty_instance"]   # "rule_id / instance_name"
            rid, _, nm = [x.strip() for x in ref.partition("/")]
            if rid not in diff_instances or nm not in diff_instances[rid]:
                problems.append(f"Stub cross-ref broken: {sec['section']}/{inst['name']} -> {ref}")

if problems:
    print("PROBLEMS:")
    for p in problems:
        print("  ", p)
    sys.exit(1)
print("coverage OK: all difficulty>=2, all non-stub corner>=1, all tags resolve, all stubs cross-ref")
