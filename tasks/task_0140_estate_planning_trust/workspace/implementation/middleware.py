"""Auth + RBAC middleware (PRD §2.1, SCAFFOLD §1.4 priorities 1-2).

Validation order on entry to every route:
  1. ERR_AUTH_REQUIRED — either header missing or empty
  2. ERR_FORBIDDEN    — role not authorised for the endpoint
"""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import ApiError


def _read_headers():
    role = request.headers.get(HEADER_USER_ROLE, "")
    user_id = request.headers.get(HEADER_USER_ID, "")
    return (role or "").strip(), (user_id or "").strip()


def require_auth(allowed_roles):
    """Decorator: enforce auth header presence + role permission.

    `allowed_roles` is the list of role strings authorised for the endpoint.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()

            # Priority 1 — header presence (PRD §2.1).
            if not role or not user_id:
                raise ApiError("ERR_AUTH_REQUIRED", 401,
                               "X-User-ID and X-User-Role headers are required.")

            # Priority 2a — role string must be a known role.
            if role not in ROLES:
                raise ApiError("ERR_FORBIDDEN", 403,
                               f"Unknown role: {role}")

            # Priority 2b — role must be authorised for the endpoint.
            if role not in allowed_set:
                raise ApiError("ERR_FORBIDDEN", 403,
                               f"Role {role} is not permitted for this endpoint.")

            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role() -> str:
    return getattr(g, "role", "")


def current_user_id() -> str:
    return getattr(g, "user_id", "")
