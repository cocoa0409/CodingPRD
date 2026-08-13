"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC."""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED_ROLE,
    HTTP_STATUS,
)

# Roles recognized by the system (PRD section 2.1). "Any" is the marker role
# covering every authenticated caller on read endpoints.
ROLES = {
    "OemNetworkAdmin",
    "OemSalesOps",
    "OemAuditor",
    "DealerUser",
    "Any",
}


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers.

    Raises ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER) when either
    header is missing or empty.
    """
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
    """Decorator: authenticate, then enforce role membership.

    The special role name "Any" means any authenticated caller presenting one
    of the recognized roles may access. A role header value that is not one of
    the recognized roles fails the role check with 403.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if "Any" in allowed:
                if role not in ROLES:
                    raise ApiError(
                        ERR_UNAUTHORIZED_ROLE,
                        HTTP_STATUS[ERR_UNAUTHORIZED_ROLE],
                        "Role not permitted for this operation",
                    )
            elif role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED_ROLE,
                    HTTP_STATUS[ERR_UNAUTHORIZED_ROLE],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
