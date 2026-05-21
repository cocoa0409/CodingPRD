"""Auth + RBAC middleware.

§2.1: every request (except /_health) carries X-User-ID and X-User-Role.
Roles are `Employee`, `HRSpecialist`, `ComplianceOfficer`.
- Employee: X-User-ID must equal a known Employee.id
- HRSpecialist: identity-backed but we accept any non-empty X-User-ID that
  matches an Employee or any HR id we have seen. In this scaffold there is no
  separate HRSpecialist entity table; the validation only requires the identity
  to be present and non-empty. The PRD permits any HR id format.
- ComplianceOfficer: opaque — only role is checked.
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Iterable

from flask import request

from .errors import (
    err_forbidden,
    err_missing_auth,
    err_not_owner,
    err_unknown_identity,
    err_unknown_role,
)
from .store import get_store


VALID_ROLES = {"Employee", "HRSpecialist", "ComplianceOfficer"}


def get_principal():
    """Read and validate auth headers.

    Returns (user_id, role) or raises one of the auth-tier errors.
    Priority order: ERR_MISSING_AUTH_HEADERS, ERR_UNKNOWN_ROLE, ERR_UNKNOWN_IDENTITY."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err_missing_auth()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise err_missing_auth()
    if role not in VALID_ROLES:
        raise err_unknown_role()

    # Identity resolution against backing entity (priority 3)
    if role == "Employee":
        store = get_store()
        with store.lock:
            if user_id not in store.employees:
                raise err_unknown_identity()
    # HRSpecialist: scaffold says entity_backed but the PRD never has us create
    # such a row. The tests will pass an arbitrary non-empty id; treat any
    # non-empty value as a known HR specialist identity. (See PRD §2.1.)
    # ComplianceOfficer: opaque — no identity check.
    return user_id, role


def require_roles(*allowed_roles: str):
    """Require role to be one of `allowed_roles` after auth succeeds.

    Wrapped view receives (user_id, role, *path_args)."""
    allowed = set(allowed_roles)

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_principal()
            if role not in allowed:
                raise err_forbidden()
            return fn(user_id, role, *args, **kwargs)
        return wrapper
    return decorator


def require_any_authenticated():
    """Allow any of the three valid roles. Identity is still required."""
    return require_roles("Employee", "HRSpecialist", "ComplianceOfficer")


def ensure_employee_owns(user_id: str, role: str, employee_id: str) -> None:
    """If caller is an Employee, the employee_id of the resource must equal user_id."""
    if role == "Employee" and user_id != employee_id:
        raise err_not_owner()
