"""Authentication and RBAC middleware."""
from __future__ import annotations

from functools import wraps
from typing import Iterable, Tuple

from flask import g, request

from core.errors import err_auth_invalid_role, err_auth_required, err_forbidden


VALID_ROLES = {"PlanAdministrator", "PayrollAgent", "Participant", "TaxAuthority"}


def _extract_identity() -> Tuple[str, str]:
    """Pull X-User-ID and X-User-Role; raise structured errors when missing/invalid."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise err_auth_required()
    if role not in VALID_ROLES:
        raise err_auth_invalid_role(f"Unknown role: {role}")
    return user_id, role


def require_roles(*roles: str):
    """Decorator factory that validates auth and constrains acting role."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_identity()
            g.user_id = user_id
            g.role = role
            if allowed and role not in allowed:
                raise err_forbidden(
                    f"Role {role} is not permitted for this operation."
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_any_authenticated():
    """Decorator that only enforces presence of auth headers."""
    return require_roles(*VALID_ROLES)


def current_user_id() -> str:
    return g.user_id


def current_role() -> str:
    return g.role
