"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.7; SCAFFOLD §1.7)."""
from flask import request

import errors

VALID_ROLES = {"SecurityOfficer", "LobbyAttendant", "Host"}


def authenticate():
    """Validate presence of X-User-ID and X-User-Role; role must be a declared role.

    Returns (user_id, user_role). Raises ERR_UNAUTHENTICATED (401) on failure.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise errors.ApiError(
            errors.ERR_UNAUTHENTICATED, 401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, user_role


def require_role(user_role, allowed_roles):
    """Enforce RBAC. Raises ERR_FORBIDDEN_ROLE (403) when role not permitted."""
    if user_role not in allowed_roles:
        raise errors.ApiError(
            errors.ERR_FORBIDDEN_ROLE, 403,
            "Role %s is not permitted for this operation" % user_role,
        )
