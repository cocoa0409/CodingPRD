"""Auth header extraction, role checking, pagination parsing (PRD §2.1, §2.3, §2.10)."""
from flask import request

from errors import err

VALID_ROLES = {"TrustAdmin", "Grantor", "Trustee", "Beneficiary"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE if the authenticated role is not in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE")


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3). Raises ERR_VALIDATION on bad types."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (sequence order), slice, return (page, pagination_meta)."""
    ordered = sorted(items, key=lambda e: e["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
