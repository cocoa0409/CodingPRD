"""Helpers shared by the route modules."""

from flask import request

from db import created_order, public_list
from errors import fail
from response import ok_list
from validation import pagination, paginate


def query_filters(table, spec):
    """Filter a table by the declared optional query parameters.

    Filter values are compared as strings so that integer-valued filters such
    as grade_level work without a second coercion step.  A filter naming a
    value no row carries simply yields an empty page.
    """
    rows = created_order(list(table.values()))
    for field in spec:
        raw = request.args.get(field)
        if raw is None:
            continue
        rows = [r for r in rows if _matches(r.get(field), raw)]
    return rows


def _matches(value, raw):
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() == str(raw).strip().lower()
    return str(value) == str(raw).strip()


def list_response(table, spec):
    limit, offset = pagination()
    rows = query_filters(table, spec)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


def query_enum(name, allowed, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s."
             % (name, ", ".join(allowed)))
    return raw
