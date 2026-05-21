"""Pagination args + list windowing."""
from flask import request

from .errors import fail


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise fail("ERR_VALIDATION", "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise fail("ERR_VALIDATION", "limit must be in [1, 100]")
    if offset < 0:
        raise fail("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def window(items: list, limit: int, offset: int) -> tuple[list, dict]:
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
