"""Auth header extraction and RBAC (PRD §2.1)."""
from functools import wraps

from flask import request

from errors import err

ROLES = {"PracticeAdmin", "FrontDeskCoordinator", "Surgeon", "BillingSpecialist"}


def get_identity():
    """Validate presence of X-User-ID / X-User-Role and a known role.

    Returns (user_id, role) or raises ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require(*allowed_roles):
    """Decorator: authenticate (401) then authorize by role (403).

    Injects `user_id` and `role` as keyword args into the handler.
    """
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
            return fn(*args, user_id=user_id, role=role, **kwargs)

        return wrapper

    return deco
