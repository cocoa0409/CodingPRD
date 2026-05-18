"""Auth / RBAC middleware — see PRD §2.1 and SCAFFOLD §1.4 priority 1/2.

X-User-ID and X-User-Role are required on every request.
- PlatformAdmin, LoanOfficer, FinanceManager, CollectionsAgent are opaque.
- Customer is entity-backed: X-User-ID must equal the acting Customer.id.
  Ownership of nested resources is enforced per-route by comparing the
  resource's customer_id against X-User-ID.
"""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import (
    ENTITY_BACKED_ROLES,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLES,
    ROLE_CUSTOMER,
)
from errors import err_forbidden_role, err_missing_or_invalid_user_context


def _read_headers():
    role = (request.headers.get(HEADER_USER_ROLE) or "").strip()
    user_id = (request.headers.get(HEADER_USER_ID) or "").strip()
    return role, user_id


def require_auth(allowed_roles):
    """Decorator: priority-1 (auth presence) + priority-2 (RBAC) gates.

    Customer ownership of nested resources is checked per-route, not here.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()
            # Priority 1: headers must be present and well-formed (non-empty).
            if not role or not user_id:
                raise err_missing_or_invalid_user_context(
                    "X-User-ID and X-User-Role headers are required."
                )
            # Priority 1 (cont.): role must be a recognised role name.
            if role not in ROLES:
                raise err_missing_or_invalid_user_context(
                    f"Unknown X-User-Role value: {role}"
                )
            # Priority 2: role must be allowed for this endpoint.
            if role not in allowed_set:
                raise err_forbidden_role(
                    f"Role {role} is not permitted for this endpoint."
                )
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role() -> str:
    return getattr(g, "role", "")


def current_user_id() -> str:
    return getattr(g, "user_id", "")


def is_customer() -> bool:
    return current_role() == ROLE_CUSTOMER
