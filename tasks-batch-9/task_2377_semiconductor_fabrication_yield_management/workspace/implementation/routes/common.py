"""Helpers shared by the route modules."""
from db import ordered
from response import ok_list
from validate import pagination


def paged(rows):
    """Default list semantics: created_at ascending, limit/offset window (PRD 2.3)."""
    limit, offset = pagination()
    rows = ordered(rows)
    total = len(rows)
    return ok_list(rows[offset:offset + limit], limit, offset, total)


def matches(row, filters):
    for key, value in filters.items():
        if value is not None and row.get(key) != value:
            return False
    return True
