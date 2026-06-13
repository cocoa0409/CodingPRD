"""Auth: extract X-User-ID / X-User-Role headers and enforce RBAC (PRD §2.1)."""
from flask import request, g

from common import ROLES
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED,
)


def authenticate():
    """Validate the user-context headers. Returns (user_id, role). Raises 401
    if a header is missing or the role is unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER[0],
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER[1],
            "missing or invalid user context header",
        )
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_role(*allowed_roles):
    """Enforce that the acting role is in allowed_roles, else 403."""
    if g.role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED[0], ERR_UNAUTHORIZED[1], "role not permitted for this operation")


def unauthorized():
    raise ApiError(ERR_UNAUTHORIZED[0], ERR_UNAUTHORIZED[1], "not permitted")
