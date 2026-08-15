"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD §2.1: missing headers OR an undeclared role value are both
ERR_UNAUTHENTICATED (401); a declared role not permitted on the endpoint is
ERR_FORBIDDEN (403).
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, HTTP_STATUS

ROLES = {
    "ProxyAdministrator",
    "TransferAgent",
    "Shareholder",
    "Broker",
    "InspectorOfElection",
}


def get_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-ID or X-User-Role header missing or empty",
        )
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-Role is not one of the declared roles",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate (401), then enforce role membership (403)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN,
                    HTTP_STATUS[ERR_FORBIDDEN],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
