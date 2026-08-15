"""Route registration plus shared list/pagination helpers.

Pagination (PRD §2.3): limit defaults to 10 (min 1, max 100), offset defaults
to 0; list meta reports limit/offset/total_count/has_more; results sorted by
created_at ascending. Filters are conjunctive exact matches.
"""
from flask import request

from db import public, sorted_by_created
from errors import ApiError, ERR_INVALID_REQUEST
from response import success_list


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(items, filters):
    """filters: list of (query_param, value_getter) — conjunctive exact match
    on stringified values."""
    filtered = list(items)
    for param, getter in filters:
        raw = request.args.get(param)
        if raw is None:
            continue
        filtered = [e for e in filtered if str(getter(e)) == raw]
    filtered = sorted_by_created(filtered)
    total = len(filtered)
    limit, offset = parse_pagination()
    page = filtered[offset:offset + limit]
    return success_list([public(e) for e in page], total, limit, offset)
