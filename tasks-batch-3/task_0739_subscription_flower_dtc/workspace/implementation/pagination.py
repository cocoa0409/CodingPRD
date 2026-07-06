"""Pagination helpers. Fields: limit (default 10, min 1, max 100), offset (default 0, min 0)."""
from flask import request
from errors import bad_request

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def parse_pagination():
    """Return (limit, offset) or raise ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise bad_request(f"limit must be in [{MIN_LIMIT},{MAX_LIMIT}]")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if offset < 0:
            raise bad_request("offset must be >= 0")

    return limit, offset


def apply_page(items, limit, offset):
    """Return items[offset:offset+limit] and total_count."""
    total = len(items)
    return items[offset:offset + limit], total
