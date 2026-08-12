"""Auth middleware (PRD §2.1, §2.6 stages 1-2).

Headers: X-User-ID and X-User-Role. Role must be one of the declared role
names, else ERR_UNAUTHENTICATED. Endpoint role lists are enforced here.
"""
from functools import wraps

from flask import request

from errors import ApiError

ROLES = {"PlatformAdmin", "BenefitsAdmin", "Employee", "Coach", "VendorManager"}


def current_identity():
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_roles(*allowed):
    """Decorator enforcing PRD §2.6 stages 1 (authentication) and 2 (role
    authorization) before the wrapped handler runs."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = current_identity()
            if not user_id or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    "Missing or invalid X-User-ID / X-User-Role headers",
                )
            if role not in allowed:
                raise ApiError(
                    "ERR_FORBIDDEN",
                    f"Role {role} is not permitted on this endpoint",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
