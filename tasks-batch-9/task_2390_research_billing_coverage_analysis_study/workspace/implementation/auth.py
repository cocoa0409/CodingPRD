"""Authentication / RBAC (PRD 2.1, validation priorities 1 and 2)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "ResearchBillingManager",
    "CoverageAnalyst",
    "ComplianceReviewer",
    "StudyCoordinator",
    "AuditLiaison",
)

ALL_ROLES = ROLES


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def actor():
    return g.user_id
