"""Pagination (PRD §2.3 / SCAFFOLD §1.0).

limit: default 10, min 1, max 100. offset: default 0. Lists sort by created_at asc.
meta surfaces limit, offset, total_count, has_more.
"""
from flask import request

import errors

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _parse_int(name, raw):
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Query parameter {name} must be an integer.")


def read_params():
    args = request.args
    if "limit" in args:
        limit = _parse_int("limit", args.get("limit"))
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.invalid_request(
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}."
            )
    else:
        limit = DEFAULT_LIMIT
    if "offset" in args:
        offset = _parse_int("offset", args.get("offset"))
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")
    else:
        offset = DEFAULT_OFFSET
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at asc (sequence tie-break) and slice; return (page, meta)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
