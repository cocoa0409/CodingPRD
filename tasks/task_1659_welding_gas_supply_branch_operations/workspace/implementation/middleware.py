"""Auth: X-User-Role header extraction (priority 1) and role gating (priority 2).

X-User-ID is an opaque operator identifier — recorded but never validated
against any persisted entity.
"""
from functools import wraps
from flask import request, g

from errors import ApiError
import db


def current_role():
    """Priority 1 gate: X-User-Role present and names a declared role."""
    role = request.headers.get("X-User-Role")
    if not role or role not in db.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-Role header is missing or does not name a declared role")
    g.user_role = role
    g.user_id = request.headers.get("X-User-ID")
    return role


def require_roles(*allowed):
    """Priority 2 gate: role must be listed for the endpoint."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = current_role()
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN", 403,
                               "Role %s is not permitted for this endpoint" % role)
            return fn(*args, **kwargs)
        return wrapper
    return deco


def body():
    """Parse the JSON request body; absent/non-object bodies yield shape errors
    at the call site via ERR_VALIDATION (missing required fields)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data
