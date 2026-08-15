"""Auth context extraction and role gating (SCAFFOLD §1.4 priorities 1-2,
PRD §2.1).

Headers: X-User-ID and X-User-Role. Roles: ComplianceOfficer, Underwriter,
Policyholder (exact spelling).
"""

from functools import wraps

from errors import err_forbidden_for_role, err_missing_auth_context
from flask import request

ROLES = ("ComplianceOfficer", "Underwriter", "Policyholder")


def get_auth():
    """Validation tier 1: headers present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err_missing_auth_context()
    if not role or role not in ROLES:
        raise err_missing_auth_context()
    return user_id, role


def require_roles(*roles):
    """Validation tier 2: caller's role admitted to the endpoint."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in roles:
                raise err_forbidden_for_role()
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
