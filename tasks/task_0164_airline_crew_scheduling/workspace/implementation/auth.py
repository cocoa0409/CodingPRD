"""Authentication, role, and RBAC middleware."""
from functools import wraps

from flask import request, g

from errors import raise_error


ALLOWED_ROLES = {"CrewScheduler", "Pilot", "FlightAttendant", "UnionSteward"}


def check_auth():
    """Validate X-User-ID + X-User-Role; set g.user_id, g.role."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not role:
        raise_error("ERR_AUTH_REQUIRED")
    if role not in ALLOWED_ROLES:
        raise_error("ERR_AUTH_INVALID_ROLE")
    g.user_id = user_id
    g.role = role
    g.union_local_id = request.headers.get("X-Union-Local-Id", "")


def require_roles(*allowed):
    """Decorator: ensures auth checks ran and current role is in allowed set."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Auth already enforced by before_request, but double-check for safety
            role = getattr(g, "role", None)
            if role not in allowed:
                raise_error("ERR_FORBIDDEN")
            return fn(*args, **kwargs)
        return wrapper
    return deco
