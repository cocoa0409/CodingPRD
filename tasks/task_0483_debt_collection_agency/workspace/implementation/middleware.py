"""Auth header extraction and RBAC enforcement (PRD 2.1, 2.10)."""
from functools import wraps

from flask import request, g

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

VALID_ROLES = {"Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System"}


def extract_user_context():
    """Validate X-User-ID and X-User-Role headers; store on flask.g.

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400) when either header
    is missing/blank or the role is not one of the five known roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(*ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       message="X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise ApiError(*ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       message="X-User-Role header missing or not a known role")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Decorator: auth header check first, then RBAC against the allowed roles."""
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            extract_user_context()
            if g.user_role not in allowed_set:
                raise ApiError(*ERR_FORBIDDEN_FOR_ROLE,
                               message="Role %s is not permitted for this operation" % g.user_role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
