"""Auth header extraction and RBAC helpers per PRD §2.1."""

from flask import g, request

from config import VALID_ROLES
from errors import (
    AppError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)


def require_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise AppError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or empty X-User-ID or X-User-Role header.",
            400,
        )
    g.user_id = user_id
    g.role = role


def require_role(*allowed_roles):
    """Allow request if g.role is in allowed_roles. 'Any' matches all valid persisted roles."""
    if "Any" in allowed_roles:
        if g.role in VALID_ROLES:
            return
        raise AppError(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"Role {g.role} is not authorized for this operation.",
            403,
        )
    if g.role not in allowed_roles:
        raise AppError(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"Role {g.role} is not authorized for this operation.",
            403,
        )
