"""Query-parameter list filtering helpers."""
from flask import request


def filter_eq(items, field, bool_field=False):
    """Filter `items` by an equality query param named `field`, when present.

    For boolean fields, accept the strings true/false (case-insensitive).
    Unknown/absent param -> no filtering. Pagination params are ignored here.
    """
    raw = request.args.get(field)
    if raw is None:
        return items
    if bool_field:
        low = raw.strip().lower()
        if low in ("true", "1"):
            want = True
        elif low in ("false", "0"):
            want = False
        else:
            # Unparseable boolean filter -> no match.
            return [i for i in items if False]
        return [i for i in items if i.get(field) is want or i.get(field) == want]
    return [i for i in items if str(i.get(field)) == raw]
