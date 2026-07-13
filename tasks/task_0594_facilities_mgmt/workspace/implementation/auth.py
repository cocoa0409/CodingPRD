"""Authentication and role authorisation (PRD 2.1, validation steps 1 and 2)."""

from functools import wraps

from flask import g, request

from errors import fail

ROLES = {
    "PlatformAdmin",
    "FacilityManager",
    "VendorTech",
    "FinanceController",
    "TenantRep",
    "SustainabilityAnalyst",
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def require(*roles):
    """Decorator: authenticate (401) then authorise the role (403)."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                fail("ERR_FORBIDDEN_ROLE")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
