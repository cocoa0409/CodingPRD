"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD §2.1 / scaffold §1.4 p1-p2:
  - X-User-Role and X-User-ID must be present and role must be a declared role
    -> ERR_UNAUTHENTICATED (401)
  - Role not permitted to invoke the endpoint -> ERR_UNAUTHORIZED (403)
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, HTTP_STATUS

ROLES = {
    "Student",
    "FrontDesk",
    "TriageScreener",
    "Counselor",
    "ReferralCoordinator",
    "ClinicalDirector",
    "Registrar",
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
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "Missing or invalid X-User-Role / X-User-ID headers",
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
                    ERR_UNAUTHORIZED,
                    HTTP_STATUS[ERR_UNAUTHORIZED],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
