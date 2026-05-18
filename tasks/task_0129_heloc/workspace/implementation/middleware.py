"""Request-scoped auth + RBAC helpers."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import HEADER_USER_ID, HEADER_USER_ROLE, ROLES, SERVICER_EXCLUSIVE_ENDPOINTS
from errors import (
    err_forbidden,
    err_missing_auth,
    err_segregation,
    err_unknown_role,
)


def _read_headers():
    role = request.headers.get(HEADER_USER_ROLE, "") or ""
    user_id = request.headers.get(HEADER_USER_ID, "") or ""
    return role.strip(), user_id.strip()


def require_auth(allowed_roles, endpoint_key: str | None = None):
    """Decorator enforcing the §1.4 auth validation order.

    Validation priority (scaffold §1.4):
      1 — ERR_MISSING_AUTH:     both headers present + non-empty
      2 — ERR_UNKNOWN_ROLE:     X-User-Role is one of ROLES
      3 — ERR_FORBIDDEN:        role authorised for this endpoint
      5 — ERR_SEGREGATION_OF_DUTIES:
                                 Originator attempted a Servicer-exclusive op
                                 (returned in place of the generic ERR_FORBIDDEN)

    Priority 4 — borrower-scoped read-ownership check — is enforced at
    the route handler level since it requires knowledge of the target
    resource's owning borrower chain.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()

            # Priority 1: header presence.
            if not role or not user_id:
                raise err_missing_auth()

            # Priority 2: role recognised.
            if role not in ROLES:
                raise err_unknown_role()

            # Priority 3 + 5: RBAC, with SoD specialisation for
            # Originator attempting a Servicer-exclusive endpoint.
            if role not in allowed_set:
                if role == "Originator" and endpoint_key in SERVICER_EXCLUSIVE_ENDPOINTS:
                    raise err_segregation()
                raise err_forbidden()

            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role() -> str:
    return getattr(g, "role", "")


def current_user_id() -> str:
    return getattr(g, "user_id", "")
