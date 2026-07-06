"""Auth + role enforcement per PRD §2.1 / §3.9."""
from __future__ import annotations

from functools import wraps
from flask import request, g

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNKNOWN_ROLE,
    ERR_FORBIDDEN,
    raise_error,
)

VALID_ROLES = {"StoreManager", "StoreClerk", "DeliveryDriver", "Customer"}


def _auth_check(required_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    # priority 1
    if not user_id or not role:
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role required")

    # priority 2
    if role not in VALID_ROLES:
        raise_error(ERR_UNKNOWN_ROLE, f"Unknown role {role}")

    # priority 3
    if required_roles and role not in required_roles:
        raise_error(ERR_FORBIDDEN, f"Role {role} not permitted")

    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Decorator: enforce priority 1–3 before hitting the handler."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _auth_check(set(roles))
            return fn(*args, **kwargs)
        return wrapper
    return deco
