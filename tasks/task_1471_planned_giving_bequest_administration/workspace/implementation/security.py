"""Auth middleware (PRD 2.1): X-User-ID + X-User-Role headers."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "GiftOfficer",
    "GiftAdministrator",
    "ComplianceOfficer",
    "EstateManager",
    "FinanceSteward",
)
ALL_ROLES = ROLES


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    401,
                    "Missing X-User-ID / X-User-Role headers, or role is not a declared role",
                )
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "Role %s is not authorized for this endpoint" % role,
                )
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
