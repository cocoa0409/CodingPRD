"""Authentication / authorisation middleware (PRD 2.1)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "SafetyEngineer",
    "ComplianceOfficer",
    "RecallOperationsManager",
    "DealerServiceManager",
    "ClaimsAuditor",
)
ALL_ROLES = ROLES


def require_roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if allowed and role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
