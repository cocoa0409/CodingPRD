"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC
(PRD 2.1, validation ladder rungs 1-2)."""

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN,
    HTTP_STATUS,
)

ALL_ROLES = (
    "CapacityController",
    "ForwarderAgent",
    "RampOperator",
    "DGInspector",
    "CustomsOfficer",
    "ClaimsAdjuster",
)


def get_auth():
    """Extract and validate the user-context headers (ladder rung 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "X-User-ID or X-User-Role header missing or empty",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate (rung 1), then enforce role membership (rung 2).

    A role header value that is not among the endpoint's declared roles —
    including a string that is not a recognized role at all — fails with
    ERR_FORBIDDEN (403).
    """

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
