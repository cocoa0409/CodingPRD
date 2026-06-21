"""Auth header extraction, RBAC, and pagination parsing.

Auth headers (PRD §2.1): X-User-ID + X-User-Role.
Roles: Anonymous, AccountHolder, ComplianceOfficer, PlatformAdmin.
"""
from flask import request

from errors import err

KNOWN_ROLES = {"Anonymous", "AccountHolder", "ComplianceOfficer", "PlatformAdmin"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Return a Principal or raise ERR_UNAUTHENTICATED.

    Both headers must be present and the role must be a recognized role name.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return Principal(user_id, role)


def require_roles(principal, allowed):
    """priority 2: role must be permitted for the operation, else ERR_FORBIDDEN_ROLE."""
    if principal.role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")


def parse_pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0.

    Out-of-range / malformed values surface ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit out of range [1,100].")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Apply offset/limit, return (page, meta_dict)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
