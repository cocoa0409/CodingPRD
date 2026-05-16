"""Authentication and RBAC helpers."""
from functools import wraps

from flask import g, request

from errors import err

ROLES = {"PlanAdmin", "BenefitsCounselor", "Beneficiary", "Auditor"}


def auth_middleware():
    """Validate headers; populate g.role / g.user_id. Raises APIError on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # Distinguish missing (header absent or user_id absent/empty) vs invalid role.
    # An empty X-User-Role string is "present but invalid" per PRD §2.1
    # ("does not match one of the four enumerated values").
    if user_id is None or role is None or not user_id:
        raise err("ERR_AUTH_MISSING", "X-User-ID or X-User-Role header missing")
    if role not in ROLES:
        raise err("ERR_AUTH_INVALID_ROLE", f"Role '{role}' is not recognised")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed_roles):
    """Decorator: ensure the current request role is one of the allowed set."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if g.role not in allowed:
                raise err("ERR_FORBIDDEN", f"Role '{g.role}' cannot access this endpoint")
            return fn(*args, **kwargs)

        return wrapped

    return deco
