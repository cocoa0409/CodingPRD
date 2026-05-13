"""Auth header extraction and RBAC checks."""

from __future__ import annotations

from functools import wraps
from flask import request, g

from errors import APIError, ERR_AUTH_MISSING, ERR_FORBIDDEN


# All recognized roles (PRD §2.1)
VALID_ROLES = {"Applicant", "Supervisor", "DeptHead", "Finance", "GeneralManager", "Admin"}


def extract_auth():
    """Pull X-User-ID and X-User-Role headers; raise ERR_AUTH_MISSING if absent/empty."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise APIError(ERR_AUTH_MISSING, "Missing authentication headers", 401)
    return user_id, role


def require_auth(allowed_roles):
    """Decorator that:
      - extracts the auth headers (or raises ERR_AUTH_MISSING)
      - checks the role is in allowed_roles (else ERR_FORBIDDEN)
      - exposes (user_id, role) via flask.g
    """
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_auth()
            if role not in VALID_ROLES or role not in allowed:
                raise APIError(ERR_FORBIDDEN, f"Role {role!r} not permitted for this endpoint", 403)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
