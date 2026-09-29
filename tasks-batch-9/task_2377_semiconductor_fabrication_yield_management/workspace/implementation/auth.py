"""Authentication and role authorisation (PRD 2.1, validation priorities 1-2)."""
from functools import wraps

from flask import g, request

from errors import fail

ROLES = (
    "ProcessEngineer",
    "QualityManager",
    "EquipmentEngineer",
    "FabPlanner",
    "YieldEngineer",
    "Operator",
)

ALL_ROLES = ROLES


def require(*roles):
    allowed = tuple(roles) if roles else ROLES

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required")
            if role not in allowed:
                fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint" % role)
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator
