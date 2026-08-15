"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD §2.1 / scaffold §1.4 p1-p2:
  - Endpoints whose roles include Anonymous may be called with NO headers
    (treated as Anonymous).
  - Otherwise both headers must be present and X-User-Role must be a declared
    role, else ERR_UNAUTHENTICATED (401).
  - SchoolLiaison callers must present X-User-ID equal to an existing
    School.id, else ERR_UNAUTHENTICATED (401) — applies to every call.
  - Role not listed for the endpoint -> ERR_UNAUTHORIZED_ROLE (403).
"""

from __future__ import annotations

from functools import wraps

from flask import request

import db
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    HTTP_STATUS,
)

ROLES = {
    "Anonymous",
    "Steward",
    "SchoolLiaison",
    "HubCoordinator",
    "Moderator",
    "NetworkAdmin",
}


def get_auth() -> tuple[str | None, str]:
    """Extract and validate the user-context headers.

    Returns (user_id, role). Headerless calls resolve to (None, "Anonymous").
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if (user_id is None or user_id.strip() == "") and (
        role is None or role.strip() == ""
    ):
        # Fully headerless call -> anonymous public traffic.
        return None, "Anonymous"

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

    if role == "SchoolLiaison" and user_id not in db.schools:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            HTTP_STATUS[ERR_UNAUTHENTICATED],
            "SchoolLiaison X-User-ID must equal an existing School id",
        )

    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce endpoint role membership."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                # Endpoints that do not list Anonymous reject unauthenticated
                # (headerless or Anonymous-marked) traffic with 401 (§2.1).
                if role == "Anonymous":
                    raise ApiError(
                        ERR_UNAUTHENTICATED,
                        HTTP_STATUS[ERR_UNAUTHENTICATED],
                        "Missing or invalid X-User-Role / X-User-ID headers",
                    )
                raise ApiError(
                    ERR_UNAUTHORIZED_ROLE,
                    HTTP_STATUS[ERR_UNAUTHORIZED_ROLE],
                    "Role not permitted for this operation",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
