"""Pagination + ownership helpers used by route modules."""
from flask import request, g

import errors

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def paginate_params():
    """Read limit/offset query params with defaults and bounds (PRD §2.3).

    limit defaults 10, min 1, max 100. offset defaults 0. Out-of-range values
    are treated as malformed list parameters -> ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.err_invalid_request("limit must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.err_invalid_request("limit out of range [1,100].")

    if offset_raw is None:
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.err_invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.err_invalid_request("offset must be >= 0.")
    return limit, offset


def sort_by_created(items):
    """Default sort: creation timestamp ascending. created_at is millisecond
    precision; ties (same ms) fall back to insertion order, which the input
    list already reflects since we iterate dict values in insertion order."""
    return sorted(items, key=lambda e: e["created_at"])


def apply_page(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def owner_guard(owner_id):
    """For Owner-role callers, enforce that owner_id == X-User-ID
    (ERR_NOT_RESOURCE_OWNER). No-op for staff/manager."""
    if g.role == "Owner" and g.user_id != owner_id:
        raise errors.err_not_resource_owner()
