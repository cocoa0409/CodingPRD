"""Auth + RBAC middleware (PRD §2.1, §2.4; SCAFFOLD §1.4 priorities 1-3).

Validation order:
  1. ERR_AUTH_MISSING_HEADERS — either header missing/empty
  2. ERR_AUTH_UNKNOWN_ROLE   — X-User-Role not in {Petitioner, Beneficiary,
                                Officer, Supervisor}
  3. ERR_FORBIDDEN           — known role lacks permission for this op
"""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import err_auth_missing, err_auth_unknown_role, err_forbidden


def _read_headers():
    role = request.headers.get(HEADER_USER_ROLE, "")
    user_id = request.headers.get(HEADER_USER_ID, "")
    return (role or "").strip(), (user_id or "").strip()


def require_auth(allowed_roles):
    """Decorator: enforce auth-header presence + role permission.

    `allowed_roles` is the list of role strings authorised for the endpoint.
    A role of "Any" (not used in this scaffold) would mean any authenticated
    role — we keep the more conservative explicit list per SCAFFOLD §1.7.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()

            # Priority 1 — header presence (either missing or empty).
            if not role or not user_id:
                raise err_auth_missing()

            # Priority 2 — role must be a known role string.
            if role not in ROLES:
                raise err_auth_unknown_role()

            # Priority 3 — role permitted for this endpoint.
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
