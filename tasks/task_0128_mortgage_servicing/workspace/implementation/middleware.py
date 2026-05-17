"""Request-scoped auth + RBAC helpers."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import ApiError, err_auth_missing, err_forbidden


def _read_headers():
    role = request.headers.get(HEADER_USER_ROLE, "")
    user_id = request.headers.get(HEADER_USER_ID, "")
    role = (role or "").strip()
    user_id = (user_id or "").strip()
    return role, user_id


def require_auth(allowed_roles):
    """Decorator: enforce auth-header presence + role permission.

    Validation order matches the scaffold's §1.4 priorities:
      1. X-User-Role present and recognised → ERR_AUTH_MISSING
      2. X-User-ID present                  → ERR_AUTH_MISSING
      3. role in allowed_roles              → ERR_FORBIDDEN
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()
            # Priority 1: role header presence + known role.
            if not role or role not in ROLES:
                raise err_auth_missing("X-User-Role header missing or invalid.")
            # Priority 2: user-id header presence.
            if not user_id:
                raise err_auth_missing("X-User-ID header missing.")
            # Priority 3: RBAC.
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
