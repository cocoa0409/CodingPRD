"""Auth header extraction and RBAC (PRD 2.1, rejection ladder steps 1-3)."""
from flask import request

from constants import ALL_ROLES
from errors import ApiError


def authenticate(allowed_roles):
    """Steps 1-3 of the rejection ladder.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(
            "ERR_MISSING_AUTH_HEADERS",
            "X-User-ID and X-User-Role headers are both required.",
        )
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "X-User-Role '%s' is not a recognised role." % role)
    if role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role '%s' is not authorised for this endpoint." % role,
        )
    return user_id, role
