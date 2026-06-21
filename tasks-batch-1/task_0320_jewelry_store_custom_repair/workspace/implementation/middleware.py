"""Auth header extraction, role checking, pagination parsing (PRD §2.1, §2.3, §2.8)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"SalesAssociate", "Goldsmith", "StoreManager", "Customer"}


def get_caller():
    """Extract and validate X-User-ID / X-User-Role headers.

    Raises ERR_MISSING_AUTH (401) if either header is missing or malformed.
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_MISSING_AUTH", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_AUTH", "Malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Role authorization (PRD §2.1). Raises ERR_FORBIDDEN_ROLE (403) if not permitted."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100. offset default 0, min 0.
    Out-of-bounds values are malformed -> ERR_INVALID_REQUEST (422).
    """
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")

    if limit is None:
        limit_val = 10
    else:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_val < 1 or limit_val > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit out of bounds (1..100)")

    if offset is None:
        offset_val = 0
    else:
        try:
            offset_val = int(offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_val < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit_val, offset_val


def paginate(records, limit, offset):
    """Sort by created_at ascending (stable via _seq), slice, return (page, meta)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta
