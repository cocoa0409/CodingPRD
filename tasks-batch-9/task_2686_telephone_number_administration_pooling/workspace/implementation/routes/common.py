"""Shared listing helpers for the route modules."""

from flask import request

OCN_PATTERN = r"^[A-Z0-9]{4}$"
STATE_PATTERN = r"^[A-Z]{2}$"
NPA_PATTERN = r"^[2-9][0-9]{2}$"
NXX_PATTERN = r"^[2-9][0-9]{2}$"
LATA_PATTERN = r"^[0-9]{3}$"
LRN_PATTERN = r"^[0-9]{10}$"
TN_PATTERN = r"^[0-9]{10}$"
PERIOD_PATTERN = r"^[0-9]{4}-H[12]$"


def as_text(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def filter_rows(rows, specs):
    """Apply exact-match query filters.  specs is a list of (param, getter)."""
    for param, getter in specs:
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        rows = [r for r in rows if as_text(getter(r)) == raw]
    return rows


def field(name):
    return lambda record: record.get(name)
