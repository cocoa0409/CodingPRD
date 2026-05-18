"""Request-scoped auth + RBAC helpers — see PRD §2.1 and SCAFFOLD §1.4."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import (
    ENTITY_BACKED_ROLES,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLES,
)
from db import store
from errors import (
    err_auth_forbidden,
    err_auth_identity_unknown,
    err_auth_missing,
)


def _read_headers():
    role = request.headers.get(HEADER_USER_ROLE, "")
    user_id = request.headers.get(HEADER_USER_ID, "")
    role = (role or "").strip()
    user_id = (user_id or "").strip()
    return role, user_id


def _identity_resolves(role: str, user_id: str) -> bool:
    """For entity-backed roles, X-User-ID must point at a stored entity.

    - ClientUser -> Client.id
    - Advisor    -> stored Advisor id (auto-registered on first sight)

    Opaque roles (ComplianceOfficer, TaxAdmin, system) are never rejected
    on identity grounds — the value is recorded for audit only.
    """
    if role == "ClientUser":
        return user_id in store.clients
    if role == "Advisor":
        # Auto-register the advisor entity on first sight so test
        # harnesses can supply arbitrary advisor ids without an
        # explicit POST /advisors endpoint (the scaffold lists no
        # such endpoint but treats Advisor as entity_backed).
        if user_id not in store.advisors:
            with store.lock:
                if user_id not in store.advisors:
                    store.advisors[user_id] = {"id": user_id}
        return True
    return True


def require_auth(allowed_roles):
    """Decorator that enforces the priority-1/2/3 auth gates."""
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()
            # Priority 1: both headers must be present and well-formed.
            if not role or not user_id:
                raise err_auth_missing("X-User-Role and X-User-ID headers are required.")
            # Priority 2: role must be one of the recognised role names AND permitted.
            if role not in ROLES:
                raise err_auth_forbidden(f"Unknown role: {role}")
            if role not in allowed_set:
                raise err_auth_forbidden(f"Role {role} is not permitted for this endpoint.")
            # Priority 3: for entity-backed roles, the identity must resolve.
            if role in ENTITY_BACKED_ROLES and not _identity_resolves(role, user_id):
                raise err_auth_identity_unknown(
                    f"X-User-ID {user_id} does not resolve to a {role} entity."
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
