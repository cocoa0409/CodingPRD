"""Diff SCAFFOLD.yaml section 1.5 endpoint table against Flask's url_map."""
import re
import sys

import yaml  # type: ignore

sys.path.insert(0, ".")
from app import app  # noqa: E402

with open("../../SCAFFOLD.yaml") as f:
    scaffold = yaml.safe_load(f)

expected = set()
for ep in scaffold["endpoints"]:
    # Flask converter syntax: {marketId} -> <marketId>
    path = re.sub(r"\{(\w+)\}", r"<\1>", ep["path"])
    expected.add((ep["method"], path))

actual = set()
for rule in app.url_map.iter_rules():
    if rule.endpoint == "static":
        continue
    for method in rule.methods:
        if method in ("HEAD", "OPTIONS"):
            continue
        actual.add((method, rule.rule))

missing = sorted(expected - actual)
extra = sorted(actual - expected)
print("expected:", len(expected))
print("actual:  ", len(actual))
if missing:
    print("MISSING (in scaffold, not in app):")
    for m, p in missing:
        print("  ", m, p)
if extra:
    print("EXTRA (in app, not in scaffold):")
    for m, p in extra:
        print("  ", m, p)
if not missing and not extra:
    print("ROUTE DIFF: %d/%d registered, no gaps" % (len(actual), len(expected)))
else:
    sys.exit(1)
