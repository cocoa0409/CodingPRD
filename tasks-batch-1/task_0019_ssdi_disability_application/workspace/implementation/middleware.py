"""Auth header extraction and RBAC."""
from functools import wraps

from flask import request

from errors import forbidden, unauthenticated

ROLES = {"Claimant", "DDSExaminer", "ALJ", "BenefitsAdmin", "SSAAdmin"}


def get_caller():
    """Extract X-User-ID and X-User-Role. Raise APIError if missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise unauthenticated()
    if role not in ROLES:
        # An unknown role value cannot be authorized for any endpoint.
        raise forbidden(f"unknown role: {role}")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: enforce auth and that caller role is in allowed_roles."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_caller()
            if role not in allowed_roles:
                raise forbidden(f"role {role} not permitted")
            return fn(*args, user_id=user_id, role=role, **kwargs)

        return wrapper

    return decorator
