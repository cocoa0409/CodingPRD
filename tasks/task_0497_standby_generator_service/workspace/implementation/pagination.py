"""Pagination (PRD §2.3): limit default 10 (min 1, max 100), offset default 0."""
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
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")


def get_pagination():
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if "limit" in request.args:
        limit = _parse_int(request.args.get("limit"), "limit")
        if limit < MIN_LIMIT:
            limit = MIN_LIMIT
        elif limit > MAX_LIMIT:
            limit = MAX_LIMIT
    if "offset" in request.args:
        offset = _parse_int(request.args.get("offset"), "offset")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
