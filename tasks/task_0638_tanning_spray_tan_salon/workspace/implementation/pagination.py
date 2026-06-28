"""Pagination parsing (PRD §2.3 / scaffold §1.0).

limit: default 10, min 1, max 100. offset: default 0.
Lists are sorted by created_at ascending unless otherwise noted; we break ties
on a monotonic insertion sequence for determinism.
"""
from flask import request

import errors
from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(raw, field):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be an integer")


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


def paginate(items, limit, offset):
    """items already sorted; return the requested page slice and total count."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
