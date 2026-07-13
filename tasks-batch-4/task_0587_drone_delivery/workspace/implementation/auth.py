"""Authentication and RBAC (PRD 2.1, order of rejection steps 1-2)."""
from functools import wraps

from flask import g, request

from errors import err

ROLES = ("Customer", "DispatchOperator", "FlightDirector", "MaintenanceTech", "PlatformAdmin")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def require(*allowed):
    """Decorator: authenticate, then authorize the acting role."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise err("ERR_FORBIDDEN_ROLE")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
