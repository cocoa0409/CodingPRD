from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def require_roles(*roles):
    """Auth priority 1 (ERR_UNAUTHENTICATED) then 2 (ERR_UNAUTHORIZED)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not role or role not in ROLES or not uid:
                raise ApiError("ERR_UNAUTHENTICATED", 401,
                               "X-User-Role header missing or does not name a declared role")
            if role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", 403,
                               "Role is not permitted for this endpoint")
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
