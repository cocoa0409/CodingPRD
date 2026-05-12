"""Auth header parsing and RBAC enforcement."""
from functools import wraps
from flask import request
from errors import APIError, E, raise_error


VALID_ROLES = {"PlatformAdmin", "Manager", "Clerk", "Recipient", "CourierCompany", "PaymentSystem"}


def get_auth():
    """Extract (user_id, role) from request headers, raising ERR_AUTH_MISSING if absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error(E.AUTH_MISSING, "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: ensure request bears valid auth and role is in allowed_roles."""
    allowed_set = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed_set:
                raise_error(E.FORBIDDEN, f"Role {role} not permitted")
            return fn(*args, **kwargs)
        return wrapped
    return deco
