"""Authentication and RBAC middleware."""
from __future__ import annotations

from functools import wraps
from typing import Tuple

from flask import g, request

from core.errors import err_invalid_role, err_missing_auth
from core.store import store
from core.utils import is_uuid


VALID_ROLES = {"TRAVELER", "MANAGER", "FINANCE_REVIEWER", "OOP_APPROVER", "ADMIN"}


def _extract_identity() -> Tuple[str, str]:
    """Pull X-User-ID and X-User-Role; raise structured errors when missing/invalid."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")

    if user_id is None or role is None:
        raise err_missing_auth()

    user_id = user_id.strip()
    role = role.strip()

    if not user_id or not role:
        raise err_missing_auth()

    if not is_uuid(user_id):
        raise err_missing_auth("X-User-ID must be a well-formed UUID.")

    if role not in VALID_ROLES:
        raise err_invalid_role(f"Unknown role: {role}")

    # For entity-backed roles, the X-User-ID must resolve to an Employee
    # whose role matches the header.
    if role != "ADMIN":
        emp = store.employees.get(user_id)
        if emp is None or emp.get("role") != role:
            raise err_invalid_role(
                "X-User-ID does not resolve to an Employee with that role."
            )

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
                raise err_invalid_role(
                    f"Role {role} is not permitted for this operation."
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_auth():
    """Decorator that enforces presence of auth headers without role filtering."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_identity()
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id() -> str:
    return g.user_id


def current_role() -> str:
    return g.role
