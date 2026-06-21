"""Pagination & list helpers."""
from flask import request

from errors import APIError, ERR_INVALID_REQUEST


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_limit_offset():
    """Parse and validate ?limit + ?offset query params.

    Out-of-range or malformed values raise ERR_INVALID_REQUEST (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = DEFAULT_LIMIT if raw_limit is None else int(raw_limit)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = DEFAULT_OFFSET if raw_offset is None else int(raw_offset)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 400, "offset must be an integer")

    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 400, "offset must be non-negative")
    return limit, offset


def slice_sorted(items, limit, offset):
    """Sort ascending by created_at then slice. Returns (page_items, total_count)."""
    items = list(items)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
