"""Request-scoped authentication + RBAC enforcement (PRD §2.1 / §2.8)."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import err_forbidden, err_unauthenticated


def _read_headers():
    role = request.headers.get(HEADER_USER_ROLE, "")
    user_id = request.headers.get(HEADER_USER_ID, "")
    return (role or "").strip(), (user_id or "").strip()


def require_auth(allowed_roles):
    """Decorator enforcing scaffold §1.4 priorities 1 & 2.

    Order:
        1. Either header missing/unparseable → ERR_UNAUTHENTICATED (401)
        2. Role not in allowed_roles for this endpoint → ERR_FORBIDDEN (403)
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()
            # ERR_UNAUTHENTICATED: both headers must be present and the role
            # must be one of the recognised role names.
            if not role or role not in ROLES or not user_id:
                raise err_unauthenticated("X-User-Role / X-User-ID required.")
            # ERR_FORBIDDEN: known role, but not allowed for this endpoint.
            if role not in allowed_set:
                raise err_forbidden(f"Role {role} is not permitted for this endpoint.")
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role() -> str:
    return getattr(g, "role", "")


def current_user_id() -> str:
    return getattr(g, "user_id", "")
