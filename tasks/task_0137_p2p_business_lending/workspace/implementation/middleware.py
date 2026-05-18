"""Request-scoped auth + RBAC helpers — see PRD §2.1 and SCAFFOLD §1.4 priorities 1–2."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from config import (
    ENTITY_BACKED_ROLES,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    ROLES,
)
from errors import err_forbidden_for_role, err_missing_user_context


def _read_headers():
    role = (request.headers.get(HEADER_USER_ROLE) or "").strip()
    user_id = (request.headers.get(HEADER_USER_ID) or "").strip()
    return role, user_id


def require_auth(allowed_roles):
    """Decorator enforcing priority-1 (header presence) and priority-2 (role)
    auth gates.

    Identity resolution for entity-backed roles happens lazily inside each
    route — it depends on the platform scope of the URL. The PRD's auth
    contract is that the role must be permitted on the endpoint; ownership
    against an entity is a per-route business check expressed via
    ERR_FORBIDDEN_FOR_ROLE.
    """
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = _read_headers()
            # Priority 1 — header presence.
            if not role or not user_id:
                raise err_missing_user_context()
            # Validate role is a recognised one and permitted.
            if role not in ROLES:
                raise err_forbidden_for_role(f"Unknown role: {role}")
            if role not in allowed_set:
                raise err_forbidden_for_role(
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
