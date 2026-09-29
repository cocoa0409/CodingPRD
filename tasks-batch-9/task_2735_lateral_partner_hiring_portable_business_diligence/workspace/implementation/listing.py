"""List-endpoint helper: default ordering, pagination and array envelope."""

from flask import request

from db import pub_list, sorted_rows
from middleware import pagination
from response import array_response


def paged(rows):
    limit, offset = pagination()
    ordered = sorted_rows(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return array_response(pub_list(page), limit, offset, total)


def eq_filter(rows, field, param=None):
    """Narrow rows by an exact string query parameter when it is supplied."""
    name = param or field
    value = request.args.get(name)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]
