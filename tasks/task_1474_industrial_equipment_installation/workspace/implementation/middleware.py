"""Auth header extraction and role checking (PRD section 2.1, validations 1-2)."""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

ROLES = ("ProjectManager", "SiteSupervisor", "SafetyOfficer", "PayrollClerk", "CustomerRep")


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not uid or not role or role not in ROLES:
                raise ApiError(ERR_UNAUTHENTICATED, 401,
                               "X-User-ID and a valid X-User-Role header are required")
            if role not in allowed:
                raise ApiError(ERR_FORBIDDEN, 403,
                               f"role {role} is not permitted to call this endpoint")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_any_role(fn):
    return require_roles(*ROLES)(fn)
