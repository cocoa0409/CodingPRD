"""Route-completeness gate: diff SCAFFOLD endpoints[] against app.url_map as
(METHOD, path) PAIRS -- never as paths alone."""

import re
import sys

import yaml

sys.path.insert(0, ".")

SCAFFOLD = ("/home/ubuntu/github/CodingPRD/tasks/"
            "task_0947_piano_tuning_moving_restoration/SCAFFOLD.yaml")

PARAM = re.compile(r"\{[^}]+\}|<[^>]+>")


def norm(path):
    return PARAM.sub("{}", path).rstrip("/") or "/"


def main():
    doc = yaml.safe_load(open(SCAFFOLD))
    declared = set()
    for ep in doc["endpoints"]:
        declared.add((ep["method"].upper(), norm(ep["path"])))

    from api import create_app
    app = create_app()
    actual = set()
    for rule in app.url_map.iter_rules():
        for method in rule.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            actual.add((method, norm(str(rule.rule))))

    missing = sorted(declared - actual)
    extra = sorted(actual - declared)
    matched = declared & actual
    print("declared = %d" % len(declared))
    print("matched  = %d" % len(matched))
    print("missing  = %d" % len(missing))
    for m in missing:
        print("   MISSING", m)
    print("extra    = %d" % len(extra))
    for e in extra:
        print("   EXTRA  ", e)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
