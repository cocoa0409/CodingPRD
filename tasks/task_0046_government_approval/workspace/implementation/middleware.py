"""Auth header extraction and RBAC helpers per PRD §2.1."""

from flask import g, request

from config import VALID_ROLES
from errors import AppError, ERR_AUTH_MISSING, ERR_FORBIDDEN


def require_auth():
    """Validate X-User-ID and X-User-Role headers; stash on flask.g."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise AppError(ERR_AUTH_MISSING,
                       "Missing X-User-ID or X-User-Role header.",
                       401)
    if role not in VALID_ROLES:
        # Unknown role -> treat as forbidden (cannot be permitted for any endpoint).
        raise AppError(ERR_FORBIDDEN, f"Unknown role '{role}'.", 403)
    g.user_id = user_id
    g.role = role


def require_role(*allowed_roles):
    if g.role not in allowed_roles:
        raise AppError(ERR_FORBIDDEN,
                       f"Role {g.role} is not authorized for this operation.",
                       403)
