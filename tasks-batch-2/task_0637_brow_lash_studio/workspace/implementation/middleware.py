"""Auth header extraction and role checking (PRD §2.1, §2.10).

Headers: X-User-ID (acting user), X-User-Role (capacity).
Roles: StudioManager, FrontDesk, LashTech, Member.
"""
from flask import request

import errors

VALID_ROLES = {"StudioManager", "FrontDesk", "LashTech", "Member"}


def get_user_context():
    """Return (user_id, role). Raise ERR_MISSING_OR_INVALID_USER_CONTEXT (401)
    if either header is absent or X-User-Role is not a known role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT, 401,
            "Missing or invalid user context headers.",
        )
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE (403) if role not in allowed set."""
    if role not in allowed:
        raise errors.ApiError(
            errors.ERR_FORBIDDEN_ROLE, 403,
            "Role not permitted for this operation.",
        )
