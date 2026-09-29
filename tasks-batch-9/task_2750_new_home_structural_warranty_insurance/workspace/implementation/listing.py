"""Query-parameter filters for the list endpoints (PRD 2.6).

An unknown enum value in a filter is not a validation error: it simply matches
no row, so the caller gets an empty page.
"""

from flask import request


def eq_filter(rows, field, param=None):
    raw = request.args.get(param or field)
    if raw is None:
        return rows
    return [row for row in rows if row.get(field) == raw]


def bool_filter(rows, field, param=None):
    raw = request.args.get(param or field)
    if raw is None:
        return rows
    text = raw.strip().lower()
    if text in ("true", "1"):
        want = True
    elif text in ("false", "0"):
        want = False
    else:
        return []
    return [row for row in rows if bool(row.get(field)) is want]
