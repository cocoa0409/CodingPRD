"""Auth header extraction and role checking (PRD SS2.1)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("PlantAdmin", "LineScheduler", "ProcessChemist", "QcInspector", "QualityManager")
ROLE_SET = frozenset(ROLES)


def require_roles(*roles):
    """Enforce: X-User-ID and X-User-Role present with a declared role
    (ERR_UNAUTHENTICATED 401), then role membership for the endpoint
    (ERR_FORBIDDEN 403)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = (request.headers.get("X-User-ID") or "").strip()
            role = (request.headers.get("X-User-Role") or "").strip()
            if not uid or not role or role not in ROLE_SET:
                raise ApiError(
                    "ERR_UNAUTHENTICATED", 401,
                    "Missing or invalid X-User-ID / X-User-Role header, or undeclared role",
                )
            if role not in roles:
                raise ApiError(
                    "ERR_FORBIDDEN", 403,
                    "Role %s is not authorized for this operation" % role,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
