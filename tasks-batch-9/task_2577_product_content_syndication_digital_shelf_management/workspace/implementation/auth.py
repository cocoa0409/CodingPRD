"""Authentication and RBAC (PRD 2.1, evaluation steps 1 and 2)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "ShelfAdmin",
    "ContentAuthor",
    "LegalReviewer",
    "BrandGovernanceApprover",
    "SyndicationOperator",
    "RetailerIntegration",
    "AccountTeamLead",
)

ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def endpoint(roles):
    """Decorator running evaluation step 1 (401) then step 2 (403)."""
    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
