"""Request-scoped auth + RBAC decorator (PRD §2.1, validations priorities 1-2)."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import err_auth_required, err_forbidden


def _read_headers():
    role = request.headers.get(HEADER_USER_ROLE, "")
    user_id = request.headers.get(HEADER_USER_ID, "")
    return (role or "").strip(), (user_id or "").strip()


def require_auth(allowed_roles):
    """Decorator: priority 1 = auth headers present; priority 2 = role permitted."""
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()
            # Priority 1: both headers present and role is recognised.
            if not role or not user_id:
                raise err_auth_required("X-User-ID and X-User-Role headers required.")
            if role not in ROLES:
                # Unrecognised role value is treated as auth missing/invalid.
                raise err_auth_required("X-User-Role header value is not recognised.")
            # Priority 2: role permitted.
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
