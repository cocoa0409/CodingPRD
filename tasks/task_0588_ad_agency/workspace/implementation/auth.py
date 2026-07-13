"""Auth + RBAC middleware (PRD 2.1, validation priorities 1-3)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("AgencyAdmin", "AccountManager", "CreativeLead", "MediaBuyer", "ClientReviewer")
ALL_ROLES = list(ROLES)


def authenticate(allowed_roles):
    """Priority 1: both headers present and non-empty.
    Priority 2: X-User-Role is one of the five recognised roles.
    Priority 3: the role is authorised for this endpoint.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.role = role


def endpoint(roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(roles)
            return fn(*args, **kwargs)

        return wrapper

    return deco
