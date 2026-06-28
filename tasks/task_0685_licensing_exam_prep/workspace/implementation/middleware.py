"""Auth header extraction & RBAC (PRD §2.1, §2.5, scaffold §1.4 priorities 1-2).

Headers: X-User-ID (acting principal id), X-User-Role (capacity).
Roles: Learner, ContentAdmin, ExamProctor, PlatformOps.
"""
from flask import request

from errors import raise_err
import errors

VALID_ROLES = {"Learner", "ContentAdmin", "ExamProctor", "PlatformOps"}


def get_auth():
    """Validate auth headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise_err(errors.ERR_UNAUTHENTICATED, "Missing or invalid auth headers")
    return user_id, role


def require_role(role, allowed):
    """Role permission check (priority 2)."""
    if role not in allowed:
        raise_err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this endpoint")


def pagination_params():
    """Parse limit/offset per PRD §2.3 (limit default 10, min 1, max 100; offset
    default 0). Out-of-range/malformed pagination is a malformed request."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise_err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(errors.ERR_INVALID_REQUEST, "limit out of range")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise_err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(errors.ERR_INVALID_REQUEST, "offset out of range")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    has_more = offset + limit < total
    return window, total, has_more
