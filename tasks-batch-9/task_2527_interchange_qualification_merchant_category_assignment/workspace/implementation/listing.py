"""Query-string filters for the collection endpoints (PRD section 2.3).

A filter value outside its enum domain simply matches no row; it is not a
malformed request.
"""

from flask import request


def _raw(param):
    value = request.args.get(param)
    if value is None:
        return None
    value = value.strip()
    return value or None


def string_filter(rows, param, field):
    wanted = _raw(param)
    if wanted is None:
        return rows
    return [r for r in rows if r.get(field) == wanted]


def bool_filter(rows, param, field):
    wanted = _raw(param)
    if wanted is None:
        return rows
    lowered = wanted.lower()
    if lowered in ("true", "1"):
        target = True
    elif lowered in ("false", "0"):
        target = False
    else:
        return []
    return [r for r in rows if bool(r.get(field)) is target]


def apply_string_filters(rows, pairs):
    for param, field in pairs:
        rows = string_filter(rows, param, field)
    return rows
