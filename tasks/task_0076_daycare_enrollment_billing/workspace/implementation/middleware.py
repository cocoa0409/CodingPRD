"""Auth header extraction and RBAC (PRD §2.1).

Headers: X-User-ID, X-User-Role.
Roles: CenterDirector, BillingAdmin, Parent, Teacher.
"""
from __future__ import annotations

from functools import wraps
from typing import Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"CenterDirector", "BillingAdmin", "Parent", "Teacher"}


def authenticate() -> None:
    """Validate the two auth headers. Raises ERR_UNAUTHENTICATED on failure.

    Sets g.user_role and g.user_id.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    if role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Unknown role")
    g.user_role = role
    g.user_id = user_id


def require_roles(*allowed):
    """Decorator: authenticate, then enforce role membership (priority 1 then 2)."""
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed_set:
                raise APIError(ERR_FORBIDDEN_ROLE, 403, "Role not permitted for this operation")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
