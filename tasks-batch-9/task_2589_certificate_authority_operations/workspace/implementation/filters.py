"""Additive collection filtering (PRD 2.3)."""

from flask import request

TRUE_WORDS = ("true", "1", "yes")
FALSE_WORDS = ("false", "0", "no")


def apply_filters(records, spec):
    """spec maps a query parameter name (identical to the record field name)
    to either "str" or "bool"."""
    result = list(records)
    for param, kind in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind == "bool":
            lowered = raw.strip().lower()
            if lowered in TRUE_WORDS:
                want = True
            elif lowered in FALSE_WORDS:
                want = False
            else:
                continue
            result = [r for r in result if bool(r.get(param)) is want]
        else:
            result = [r for r in result if r.get(param) == raw]
    return result
