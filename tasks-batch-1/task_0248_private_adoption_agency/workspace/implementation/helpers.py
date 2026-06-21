"""Shared helpers: pagination, path-id resolution, FK resolution, listing."""
from flask import request

import db
import errors


def parse_pagination():
    """Validate & return (limit, offset). Priority 3: ERR_INVALID_PAGINATION.

    limit defaults to 10 (min 1, max 100); offset defaults to 0 (min 0). Any
    non-integer, limit<1, limit>100, or offset<0 is rejected.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_PAGINATION, "limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be an integer.")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be >= 0.")

    return limit, offset


def paginate(rows, limit, offset):
    """Sort by creation order (_seq asc) and slice. Returns (page, pagination_meta)."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def get_path(store, resource_id):
    """Resolve a path-id against a store. Priority 4: ERR_NOT_FOUND."""
    rec = store.get(resource_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Referenced resource does not exist.")
    return rec


def resolve_fk(store, fk_id):
    """Resolve a body FK. Priority 5: ERR_REFERENCED_RESOURCE_NOT_FOUND."""
    rec = store.get(fk_id)
    if rec is None:
        raise errors.err(errors.ERR_REFERENCED_RESOURCE_NOT_FOUND,
                         "A referenced resource in the request body does not exist.")
    return rec
