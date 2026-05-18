"""Request-scoped auth + RBAC enforcement (SCAFFOLD §1.4 priorities 1-3).

Validation order — failures raise immediately:
    1. X-User-Role present, non-empty                  → ERR_AUTH_MISSING
    1. X-User-ID present, non-empty                    → ERR_AUTH_MISSING
    2. X-User-Role in {Customer, ComplianceOfficer,
                       PlatformAdmin}                  → ERR_AUTH_INVALID_ROLE
    3. Role authorised for this endpoint per RBAC      → ERR_FORBIDDEN

Ownership checks (priority 9, ERR_OWNERSHIP_VIOLATION) live in the
route helpers because they need the resolved resource.
"""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import err_auth_invalid_role, err_auth_missing, err_forbidden


def _read_headers():
    role = (request.headers.get(HEADER_USER_ROLE, "") or "").strip()
    user_id = (request.headers.get(HEADER_USER_ID, "") or "").strip()
    return role, user_id


def require_auth(allowed_roles):
    """Decorator: enforce header presence, role validity, and RBAC.

    `allowed_roles` is either a single role string or an iterable of
    role strings sourced from SCAFFOLD endpoints[].roles.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()
            # Priority 1: both headers must be present and non-empty.
            if not role or not user_id:
                raise err_auth_missing()
            # Priority 2: role must be one of the three recognised values.
            if role not in ROLES:
                raise err_auth_invalid_role()
            # Priority 3: role must be allowed for this endpoint.
            if role not in allowed_set:
                raise err_forbidden()
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return deco
