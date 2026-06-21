"""Auth header extraction and RBAC, per PRD §2.1.

Every request carries X-User-ID and X-User-Role. Roles: FacilityManager,
FacilityStaff, Owner. FacilityManager/FacilityStaff identities are opaque;
Owner identity is the acting Owner.id.
"""
from functools import wraps
from flask import request, g

import errors

VALID_ROLES = {"FacilityManager", "FacilityStaff", "Owner"}


def authenticate():
    """Validate auth headers. Raises ApiError. Populates g.user_id / g.role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.err_missing_auth()
    if role not in VALID_ROLES:
        raise errors.err_invalid_role()
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce role membership (ERR_FORBIDDEN)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise errors.err_forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco
