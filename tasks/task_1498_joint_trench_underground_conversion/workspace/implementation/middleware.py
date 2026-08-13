"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD section 2.1: both headers are mandatory; the role must name one of
the five declared roles. UtilityCoordinator identity is entity-backed: its
X-User-ID is the id of the acting UtilityParticipation.
"""

from __future__ import annotations

from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, HTTP_STATUS

ROLES = {
    "ProgramManager",
    "RightOfWayAgent",
    "UtilityCoordinator",
    "ConversionContractor",
    "FinanceAnalyst",
}

ANY_AUTHENTICATED = "Any"


def get_auth() -> tuple[str, str]:
    """Extract and validate the user-context headers."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-Role header missing or not a declared role",
        )
    if user_id is None or user_id.strip() == "":
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-ID header missing",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce endpoint role membership.

    The marker "Any" means any authenticated caller presenting one of the
    five recognized roles may access.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if ANY_AUTHENTICATED not in allowed and role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN,
                    HTTP_STATUS[ERR_FORBIDDEN],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def forbid(message: str = "Role not permitted for this operation") -> None:
    raise ApiError(ERR_FORBIDDEN, HTTP_STATUS[ERR_FORBIDDEN], message)
