"""Authentication and authorization (PRD 2.1, evaluation classes 1-2)."""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = [
    "OwnerEngineer",
    "ContractorOps",
    "SurveyParty",
    "EnvironmentalMonitor",
    "SiteOperator",
]


def require_roles(*roles):
    """Class 1 (authentication) then class 2 (authorization)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ALL_ROLES:
                raise ApiError(
                    ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers are required and the role "
                    "must be one of the five declared roles",
                    401,
                )
            if role not in roles:
                raise ApiError(
                    ERR_FORBIDDEN,
                    "Role %s is not authorized for this endpoint" % role,
                    403,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
