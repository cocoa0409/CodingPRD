"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD section 2.1:
  - X-User-ID and X-User-Role must both be present and the role must be one of
    the four declared roles -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  - Role not permitted for the endpoint -> ERR_INSUFFICIENT_PERMISSIONS (403)
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    HTTP_STATUS,
)

ROLES = {
    "IntakeCoordinator",
    "ThreatAssessor",
    "TeamLead",
    "DistrictAdministrator",
}


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or user_id.strip() == ""
        or role is None
        or role.strip() == ""
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce role membership."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
