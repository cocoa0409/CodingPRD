"""Auth header extraction and RBAC (PRD §2.1)."""
from flask import request

import errors
from errors import ApiError

ROLES = {"Booker", "BoxOffice", "FloorManager", "Patron", "Performer"}


def get_identity():
    """Returns (user_id, role). Raises ERR_MISSING_AUTH if either header absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(errors.ERR_MISSING_AUTH, 401,
                       "X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_roles(role, allowed):
    """Priority-2 RBAC check. Raises ERR_ROLE_FORBIDDEN if role not allowed."""
    if role not in allowed:
        raise ApiError(errors.ERR_ROLE_FORBIDDEN, 403,
                       "Role %s is not permitted for this operation" % role)
