"""List pagination helper (limit/offset)."""
from flask import request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def _to_int(val, default):
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def get_limit_offset():
    limit = _to_int(request.args.get("limit"), DEFAULT_LIMIT)
    offset = _to_int(request.args.get("offset"), 0)
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """items: full pre-sorted list. Returns (page, limit, offset, total_count)."""
    limit, offset = get_limit_offset()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
