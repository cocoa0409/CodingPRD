"""Pagination helpers: limit/offset/total_count/has_more."""

from flask import request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def parse_pagination():
    """Return (limit, offset) clamped to limits."""
    try:
        limit_raw = request.args.get("limit")
        limit = int(limit_raw) if limit_raw is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT

    try:
        offset_raw = request.args.get("offset")
        offset = int(offset_raw) if offset_raw is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    if offset < 0:
        offset = 0

    return limit, offset


def paginate(items, limit, offset):
    """Slice items and return (page, meta)."""
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
