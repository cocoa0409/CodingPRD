"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD §2.1 / scaffold §1.4 p1-p2:
  - X-User-Role and X-User-ID must be present and the role must be one of the
    five declared roles -> ERR_UNAUTHENTICATED (401)
  - Role not in the endpoint's authorized list -> ERR_FORBIDDEN_ROLE (403)
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, HTTP_STATUS

ROLES = {
    "OriginatorOps",
    "OdfiUnderwriter",
    "OdfiOperations",
    "OdfiRiskOfficer",
    "OdfiFinance",
}

ALL_ROLES = (
    "OriginatorOps",
    "OdfiUnderwriter",
    "OdfiOperations",
    "OdfiRiskOfficer",
    "OdfiFinance",
)


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
    """Decorator: authenticate, then enforce endpoint role membership."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_ROLE,
                    HTTP_STATUS[ERR_FORBIDDEN_ROLE],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
