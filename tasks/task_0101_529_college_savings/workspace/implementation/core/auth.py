"""Auth headers, role parsing, and RBAC decorator."""

from functools import wraps
from flask import request, g
from core.errors import raise_error


VALID_ROLES = {"Donor", "Beneficiary", "PlanAdministrator"}


def parse_auth():
    """Read X-User-ID and X-User-Role from request, set g.user_id and g.user_role.

    Raises ERR_AUTH_MISSING or ERR_AUTH_INVALID_ROLE.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_error("ERR_AUTH_MISSING", "Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise_error("ERR_AUTH_INVALID_ROLE", f"X-User-Role '{user_role}' is invalid")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles):
    """Decorator: only the listed roles may invoke the endpoint."""
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.user_role not in roles:
                raise_error("ERR_FORBIDDEN", f"Role {g.user_role} is not permitted")
            return fn(*args, **kwargs)
        return wrapped
    return decorator
