"""Auth header extraction and role checking, per PRD §2.1."""

from functools import wraps

from flask import request

import errors

VALID_ROLES = {"NetworkManager", "ComplianceOfficer", "Regulator", "ProviderRep", "Member"}

ALL_ROLES = ["NetworkManager", "ComplianceOfficer", "Regulator", "ProviderRep", "Member"]


def get_caller():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.err_missing_context()
    return user_id, role


def require_roles(*roles):
    """Decorator: validate headers, then check the caller's role is allowed."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_caller()
            if role not in roles:
                raise errors.err_forbidden()
            return fn(user_id=user_id, role=role, *args, **kwargs)
        return wrapper
    return decorator
