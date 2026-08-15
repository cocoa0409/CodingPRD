"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

PRD §2.1: both headers required; an unrecognized role is rejected with
ERR_MISSING_OR_INVALID_USER_CONTEXT (400). A recognized role not permitted
for the operation is rejected with ERR_FORBIDDEN (403).
"""

from __future__ import annotations

from functools import wraps

from flask import g, request

import db
from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT,
    ERR_FORBIDDEN,
)

ROLES = (
    "SalesRep",
    "BranchManager",
    "CreditManager",
    "WarehouseManager",
    "Dispatcher",
    "RebateClerk",
    "Contractor",
)


def get_auth() -> tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or user_id.strip() == ""
        or role is None
        or role.strip() == ""
        or role not in ROLES
    ):
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT,
            "X-User-ID or X-User-Role header missing, or role not recognized",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Authenticate, then enforce role membership for the endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if allowed and role not in allowed:
                raise_err(ERR_FORBIDDEN, "Role not permitted for this operation")
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def atomic(fn):
    """Serialize mutations so all side effects of a request apply atomically."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        with db.lock:
            return fn(*args, **kwargs)

    return wrapper
