"""Auth middleware. Validates X-User-ID + X-User-Role headers."""
from functools import wraps
from flask import request

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


KNOWN_ROLES = {
    "HRClerk",
    "PayrollPreparer",
    "PayrollApprover",
    "ComplianceOfficer",
    "PlatformAdmin",
}


def get_user_id():
    return request.headers.get("X-User-ID")


def get_user_role():
    return request.headers.get("X-User-Role")


def authenticate_request():
    """Raises APIError(ERR_UNAUTHENTICATED, 401) if auth headers are missing/invalid.

    Per PRD §2.1: both X-User-ID and X-User-Role are required.
    Both must be present; X-User-Role must be one of KNOWN_ROLES.
    """
    user_id = get_user_id()
    role = get_user_role()
    if not user_id or not role:
        raise APIError(ERR_UNAUTHENTICATED, 401, "X-User-ID and X-User-Role headers are required")
    if role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "unrecognized role")


def require_roles(*allowed_roles):
    """Decorator: assert the caller's role is in the allowed set."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Auth is enforced by app-level before_request; here we add RBAC.
            role = get_user_role()
            if role not in allowed:
                raise APIError(ERR_FORBIDDEN, 403, "role not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
