"""Auth middleware and RBAC enforcement."""

from functools import wraps
from flask import request, g

from errors import APIError, raise_error


VALID_ROLES = {"Applicant", "MarketplaceAdmin", "Insurer", "CustomerService"}


def auth_required(allowed_roles=None):
    """Decorator: require X-User-ID and X-User-Role headers; check allowed_roles.

    allowed_roles: iterable of role strings; if None, all valid roles allowed.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role:
                raise_error("ERR_AUTH_REQUIRED")
            if user_role not in VALID_ROLES:
                raise_error("ERR_FORBIDDEN")
            if allowed_roles is not None and user_role not in allowed_roles:
                raise_error("ERR_FORBIDDEN")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
