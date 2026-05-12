"""Pagination helpers."""

from flask import request

from errors import ERR_BAD_REQUEST, raise_error

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error(ERR_BAD_REQUEST, "limit must be integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_error(ERR_BAD_REQUEST, f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if raw_offset is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error(ERR_BAD_REQUEST, "offset must be integer")
        if offset < 0:
            raise_error(ERR_BAD_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Items already sorted; slice and return (page, total_count)."""
    total = len(items)
    page = items[offset : offset + limit]
    return page, total


def sort_by_created_at_asc(items):
    return sorted(items, key=lambda x: (x.get("created_at") or "", x.get("id") or ""))
