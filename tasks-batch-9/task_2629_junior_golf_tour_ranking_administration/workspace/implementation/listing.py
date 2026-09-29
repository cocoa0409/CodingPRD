"""Shared filtering / ordering / pagination for list endpoints."""
from flask import request

import validate
from envelope import list_response
from store import db, ordered, public


def _matches(value, wanted):
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() == wanted.strip().lower()
    if isinstance(value, int):
        try:
            return value == int(wanted.strip(), 10)
        except (TypeError, ValueError):
            return False
    if isinstance(value, float):
        try:
            return value == float(wanted.strip())
        except (TypeError, ValueError):
            return False
    return str(value) == wanted


def collect(collection, filter_fields):
    """Ordered rows of a collection narrowed by the declared query filters."""
    rows = ordered(list(getattr(db, collection).values()))
    args = request.args
    for param in filter_fields:
        if param not in args:
            continue
        wanted = args.get(param)
        if wanted is None or wanted == "":
            continue
        rows = [r for r in rows if _matches(r.get(param), wanted)]
    return rows


def page(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response([public(r) for r in window], total, limit, offset)


def listing(collection, filter_fields):
    limit, offset = validate.pagination()
    rows = collect(collection, filter_fields)
    return page(rows, limit, offset)
