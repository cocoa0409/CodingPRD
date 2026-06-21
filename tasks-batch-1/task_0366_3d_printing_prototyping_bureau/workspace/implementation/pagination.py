"""Pagination parsing for list endpoints (PRD §2.3, SCAFFOLD §1.0).

limit: default 10, min 1, max 100.
offset: default 0.
Out-of-range or non-integer values -> ERR_INVALID_REQUEST.
List results are sorted by created_at ascending (oldest first) unless an
endpoint states otherwise.
"""

from flask import request

import errors

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = LIMIT_DEFAULT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.invalid_request("limit out of range [1,100]")

    if offset_raw is None:
        offset = OFFSET_DEFAULT
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


def paginate(items):
    """Sort by created_at asc and apply limit/offset. Returns (page, limit,
    offset, total_count)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
