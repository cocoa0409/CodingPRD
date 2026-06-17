"""Pagination (PRD §2.3): limit (default 10, min 1, max 100), offset (default 0).
List responses sorted by created_at ascending unless stated otherwise."""
from flask import request

import errors
from errors import err

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(raw, name):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err(errors.ERR_INVALID_REQUEST, "Query param %s must be an integer" % name)


def get_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        limit = _parse_int(limit_raw, "limit")
        if limit < MIN_LIMIT:
            limit = MIN_LIMIT
        elif limit > MAX_LIMIT:
            limit = MAX_LIMIT

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        offset = _parse_int(offset_raw, "offset")
        if offset < 0:
            offset = 0

    return limit, offset


def apply_pagination(records):
    """Sort by created_at ASC, return (page, limit, offset, total_count)."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
