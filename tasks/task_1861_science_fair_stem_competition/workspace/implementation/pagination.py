"""Pagination helpers per scaffold response_envelope:
fields limit/offset/total_count/has_more; defaults limit=10 (min 1, max 100),
offset 0. Lists sorted by created_at ascending unless otherwise specified.
"""

from flask import request
from errors import raise_err, ERR_INVALID_REQUEST


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(items, serializer, limit, offset):
    """Sort by created_at ASC, apply offset/limit, return
    (page_dicts, total_count)."""
    sorted_items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    return [serializer(x) for x in page], total
