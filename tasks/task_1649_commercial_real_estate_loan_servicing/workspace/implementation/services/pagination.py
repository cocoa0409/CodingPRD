"""limit/offset pagination per scaffold pagination_defaults."""
from flask import request

import errors

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = DEFAULT_LIMIT
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.invalid_request("limit out of range [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
