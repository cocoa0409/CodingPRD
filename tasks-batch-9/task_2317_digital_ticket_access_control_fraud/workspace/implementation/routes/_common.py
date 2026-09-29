"""Helpers shared by the route modules."""

from db import public
from middleware import paging
from response import ok_list


def paginated(rows):
    """PRD 2.3: total_count is computed before limit/offset are applied."""
    limit, offset = paging()
    total = len(rows)
    page = rows[offset: offset + limit]
    return ok_list([public(r) for r in page], total, limit, offset)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def filter_bool(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if bool(r.get(field)) is value]
