"""Offset/limit pagination (§2.3)."""
from flask import request

from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "%s must be an integer" % name)


def paginate(items):
    """Apply limit/offset from query params. Returns (page_items, meta_dict)."""
    total = len(items)

    limit_raw = request.args.get("limit")
    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        limit = _parse_int(limit_raw, "limit")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise err("ERR_VALIDATION", "limit out of range")

    offset_raw = request.args.get("offset")
    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        offset = _parse_int(offset_raw, "offset")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset out of range")

    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
