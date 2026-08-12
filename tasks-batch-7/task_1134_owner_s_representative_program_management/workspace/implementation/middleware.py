"""Auth middleware: X-User-Role / X-User-ID extraction and RBAC."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
)

ROLES = ("OwnerRepPM", "OwnerRepExecutive", "Owner")


def get_auth():
    """Return (user_id, role) or raise ApiError(400)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role or X-User-ID header missing/empty, or role not declared",
            400,
        )
    return user_id, role


def require_roles(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "Authenticated role is not in the endpoint's roles list",
            403,
        )
    return user_id, role
