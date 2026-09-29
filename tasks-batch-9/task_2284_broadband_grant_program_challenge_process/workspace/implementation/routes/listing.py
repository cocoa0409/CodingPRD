"""Shared list-endpoint helper."""

from db import sort_rows
from response import list_response


def paginated(rows, limit, offset):
    ordered = sort_rows(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return list_response(page, limit, offset, total)
