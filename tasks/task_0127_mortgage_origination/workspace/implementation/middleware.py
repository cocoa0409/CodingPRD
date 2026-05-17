"""Auth & RBAC middleware (PRD §2.1, SCAFFOLD validations priority 1-2)."""

from flask import g, request

from config import VALID_ROLES
from errors import (
    AppError,
    ERROR_STATUS,
    ERR_AUTH_REQUIRED,
    ERR_FORBIDDEN_ROLE,
)


def require_auth():
    """Validate X-User-ID and X-User-Role presence (priority 1) and role membership (priority 2)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise AppError(
            ERR_AUTH_REQUIRED,
            "Missing or empty X-User-ID header.",
            ERROR_STATUS[ERR_AUTH_REQUIRED],
        )
    if not role or not isinstance(role, str) or not role.strip():
        raise AppError(
            ERR_AUTH_REQUIRED,
            "Missing or empty X-User-Role header.",
            ERROR_STATUS[ERR_AUTH_REQUIRED],
        )

    role = role.strip()
    if role not in VALID_ROLES:
        raise AppError(
            ERR_FORBIDDEN_ROLE,
            f"Role {role!r} is not a recognised role.",
            ERROR_STATUS[ERR_FORBIDDEN_ROLE],
        )

    g.user_id = user_id.strip()
    g.role = role


def require_role(*allowed_roles):
    """Reject the request unless g.role is in allowed_roles."""
    if g.role not in allowed_roles:
        raise AppError(
            ERR_FORBIDDEN_ROLE,
            f"Role {g.role} is not authorised for this operation.",
            ERROR_STATUS[ERR_FORBIDDEN_ROLE],
        )
