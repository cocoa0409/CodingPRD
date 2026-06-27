"""Auth header extraction, RBAC, pagination (§1.4 / PRD §2.1, §2.3)."""

from flask import request

import errors

ROLES = {"PlatformAdmin", "UnderwritingOfficer", "FundingOfficer", "CollectionsOfficer"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED (401) when either header is missing/blank or the
    role is not a recognised role name.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated("Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise errors.unauthenticated(f"Unknown role: {role}")
    return user_id, role


def authorize(role, allowed_roles):
    """Raise ERR_UNAUTHORIZED (403) when role is not in allowed_roles."""
    if role not in allowed_roles:
        raise errors.unauthorized(
            f"Role {role} is not permitted for this operation")


ALL_ROLES = ("PlatformAdmin", "UnderwritingOfficer", "FundingOfficer", "CollectionsOfficer")


def paginate(items):
    """Apply limit/offset query params to an already-sorted list.

    Returns (page_items, pagination_meta). Defaults: limit=10 (min 1, max 100),
    offset=0. Out-of-range / malformed values raise ERR_INVALID_REQUEST.
    """
    limit = _parse_pos_int("limit", default=10, minimum=1, maximum=100)
    offset = _parse_pos_int("offset", default=0, minimum=0, maximum=None)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def _parse_pos_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Query parameter {name} must be an integer")
    if val < minimum:
        raise errors.invalid_request(f"Query parameter {name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"Query parameter {name} must be <= {maximum}")
    return val
