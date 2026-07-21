"""Authentication / RBAC / ownership helpers (PRD 2.1, 2.9)."""
from functools import wraps

from flask import request, g

from constants import KNOWN_ROLES
from errors import ApiError


def require(*roles):
    """Auth (401) + role authorization (403) guard, in that order."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in KNOWN_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def body():
    """Return the JSON body as a dict (empty dict if absent/invalid)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
