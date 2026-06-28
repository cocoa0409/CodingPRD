"""Auth header extraction and RBAC (PRD 2.1, 2.7).

Headers: X-User-ID (acting user) and X-User-Role (operational capacity). Both
mandatory and well-formed, else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER. Role
must be one of exactly five values, else (malformed role) the same header error.
When headers are present/well-formed but role not permitted for the operation,
ERR_INSUFFICIENT_PERMISSIONS.
"""
from functools import wraps

from flask import request, g

import errors
from errors import ApiError

ROLES = {"OrderingProvider", "Dispatcher", "Phlebotomist", "LabOps", "BillingAgent"}


def extract_user_context():
    """Validate the two mandatory headers. Returns (user_id, role) or raises."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        errors.fail(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers are required.")
    if not isinstance(user_id, str) or not user_id.strip():
        errors.fail(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID header is malformed.")
    if role not in ROLES:
        errors.fail(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-Role header is malformed.")
    return user_id, role


def require_roles(*allowed):
    """Decorator: validate headers (priority 1), then role permission (priority 2)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_user_context()
            g.user_id = user_id
            g.role = role
            if role not in allowed:
                errors.fail(errors.ERR_INSUFFICIENT_PERMISSIONS,
                            "Role %s is not permitted for this operation." % role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
