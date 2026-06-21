"""Pagination parameter parsing and sort/slice for list endpoints."""

from flask import request
from errors import raise_api


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    """Returns (limit, offset). Raises ERR_INVALID_REQUEST on malformed values."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise_api(
                "ERR_INVALID_REQUEST",
                f"limit must be in [{MIN_LIMIT}, {MAX_LIMIT}]",
            )

    if raw_offset is None or raw_offset == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_api("ERR_INVALID_REQUEST", "offset must be non-negative")

    return limit, offset


def slice_sorted(items: list, limit: int, offset: int):
    """Sort by created_at ascending (then id as tiebreaker) and slice."""
    sorted_items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(sorted_items)
    page = sorted_items[offset: offset + limit]
    return page, total
