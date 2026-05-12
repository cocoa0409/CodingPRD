"""Auth header extraction and RBAC helpers."""

from flask import request, g

from errors import (
    AppError,
    ERR_MISSING_AUTH_HEADERS,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from config import VALID_ROLES


def require_auth():
    """Validate X-User-ID and X-User-Role headers. Stash in flask.g."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise AppError(
            ERR_MISSING_AUTH_HEADERS,
            "Missing X-User-ID or X-User-Role header.",
            400,
        )
    if role not in VALID_ROLES:
        raise AppError(
            ERR_MISSING_AUTH_HEADERS,
            "Unknown X-User-Role value.",
            400,
        )
    g.user_id = user_id
    g.role = role


def require_role(*allowed_roles):
    """Verify the authenticated role is in the allowed set."""
    if g.role not in allowed_roles:
        raise AppError(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"Role {g.role} is not authorized for this operation.",
            403,
        )
