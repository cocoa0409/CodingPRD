"""Pagination helpers."""

from flask import request

from errors import raise_error, ERR_INVALID_PAGINATION


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_PAGINATION,
                    "limit and offset must be integers")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise_error(ERR_INVALID_PAGINATION,
                    f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}]")
    if offset < 0:
        raise_error(ERR_INVALID_PAGINATION, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
