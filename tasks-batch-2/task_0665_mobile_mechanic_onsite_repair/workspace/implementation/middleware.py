"""Auth header extraction, RBAC, pagination parsing (PRD §2.1, §2.3, §2.10)."""
from flask import request

import errors

VALID_ROLES = {"Customer", "Mechanic", "Dispatcher", "FleetManager", "PlatformAdmin"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    Both headers must be present, non-empty, and the role must be one of the
    five recognised roles, else ERR_UNAUTHENTICATED (priority 1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """RBAC check (priority 2). Raise ERR_FORBIDDEN_ROLE if role not allowed."""
    if role not in allowed:
        raise errors.forbidden_role()


def parse_pagination():
    """Parse limit/offset query params with defaults (limit=10 min 1 max 100, offset=0).

    Invalid pagination values are clamped/defaulted rather than rejected.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            limit = 10
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return the page slice + total."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
