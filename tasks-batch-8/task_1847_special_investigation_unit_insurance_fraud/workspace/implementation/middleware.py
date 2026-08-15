"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

PRD §2.1: every request carries X-User-ID and X-User-Role. Missing or empty
headers yield ERR_UNAUTHENTICATED (401). A role not permitted on the endpoint
yields ERR_UNAUTHORIZED (403). The four recognized roles are Adjuster,
SIUManager, SIUInvestigator, SIUComplianceOfficer.
"""

from __future__ import annotations

from functools import wraps

from flask import request

from constants import ALL_ROLES
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    HTTP_STATUS,
)


def get_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or str(user_id).strip() == ""
        or role is None
        or str(role).strip() == ""
    ):
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "X-User-ID or X-User-Role header missing or malformed",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Authenticate, then enforce role membership.

    The pseudo-role "All" admits any of the four recognized roles; a role value
    outside the recognized set is not permitted on any endpoint (403).
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if "All" in allowed:
                if role not in ALL_ROLES:
                    raise ApiError(
                        ERR_UNAUTHORIZED,
                        HTTP_STATUS[ERR_UNAUTHORIZED],
                        "Role not permitted for this endpoint",
                    )
            elif role not in allowed:
                raise ApiError(
                    ERR_UNAUTHORIZED,
                    HTTP_STATUS[ERR_UNAUTHORIZED],
                    "Role not permitted for this endpoint",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
