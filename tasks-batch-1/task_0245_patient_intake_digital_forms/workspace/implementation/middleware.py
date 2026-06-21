"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The four recognized roles
are spelled exactly: ClinicAdmin, FrontDeskStaff, Patient, BillingClerk.
Identity is opaque — X-User-ID is never matched against any entity id.
"""
from functools import wraps

from flask import request

from errors import (
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

VALID_ROLES = {"ClinicAdmin", "FrontDeskStaff", "Patient", "BillingClerk"}


def get_user_context():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    # Missing or malformed header -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "Missing or invalid X-User-ID header")
    if not user_role or user_role not in VALID_ROLES:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "Missing or invalid X-User-Role header")
    return user_id, user_role


def require_roles(*allowed_roles):
    """Decorator: validate user-context headers (priority 1) then role (priority 2)."""
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _user_id, user_role = get_user_context()
            if user_role not in allowed:
                raise err(ERR_INSUFFICIENT_PERMISSIONS,
                          "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
