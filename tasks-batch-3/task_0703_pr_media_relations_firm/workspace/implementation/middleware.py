"""Auth header extraction and RBAC (PRD 2.1, 2.8).

Every request must carry X-User-ID and X-User-Role. If X-User-Role is missing or
not one of the four declared roles -> ERR_UNAUTHENTICATED (401). If the role is
recognized but not permitted for the operation -> ERR_FORBIDDEN (403).

Authorization is by role alone; X-User-ID is opaque and never compared to any
entity id for ownership.
"""
from functools import wraps

from flask import request

from errors import err

ROLES = {"AccountManager", "MediaSpecialist", "SchedulingCoordinator", "PlatformAdmin"}


def authorize(allowed_roles):
    """Decorator enforcing auth (priority 1) then RBAC (priority 2)."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            # Priority 1: authentication — header present and a declared role.
            if not role or role not in ROLES:
                raise err("ERR_UNAUTHENTICATED",
                          "X-User-Role header missing or not a declared role")
            # Priority 2: authorization — role permitted for this operation.
            if role not in allowed:
                raise err("ERR_FORBIDDEN",
                          "Role not permitted for this operation")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
