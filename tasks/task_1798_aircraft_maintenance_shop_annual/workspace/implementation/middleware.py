"""Auth middleware (PRD 2.1) and per-endpoint RBAC (PRD section 4).

Headers: X-User-ID and X-User-Role are mandatory; the role must be one of
ShopManager, Mechanic, Owner, PartsClerk.  Missing headers or an unknown role
-> 401 ERR_UNAUTHENTICATED; an authenticated role not listed for the endpoint
-> 403 ERR_UNAUTHORIZED.
"""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("ShopManager", "Mechanic", "Owner", "PartsClerk")


def require_roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not role or not uid or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_role = role
            g.user_id = uid
            return fn(*args, **kwargs)

        return wrapper

    return decorator
