"""Auth / RBAC helpers (PRD §2.1)."""
from __future__ import annotations

from functools import wraps
from typing import Iterable

from flask import request

from app.errors import APIError, api_error


VALID_ROLES = {"Customer", "AdminOps", "PaymentAdapter", "LogisticsAdapter", "VetAdapter"}


def get_user_context():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise api_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "Missing or invalid X-User-ID / X-User-Role header",
        )
    return user_id, role


def require_role(*roles: str):
    """Decorator factory that enforces authentication + role membership."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_user_context()
            if role not in allowed:
                raise api_error("ERR_INSUFFICIENT_PERMISSIONS", f"Role {role} not allowed")
            return fn(*args, user_id=user_id, role=role, **kwargs)

        return wrapper

    return decorator


def assert_customer_owns(customer_id: str, user_id: str, role: str) -> None:
    """If the actor is a Customer, ensure X-User-ID == customer_id."""
    if role == "Customer" and customer_id != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS", "Cross-customer access denied")
