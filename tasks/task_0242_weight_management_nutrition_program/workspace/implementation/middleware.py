"""Auth + RBAC (PRD 2.1).

Headers: X-User-ID and X-User-Role. Roles: ProgramAdmin, Clinician,
BillingAgent, Coach, Member. Auth precedes authorization: missing/invalid
header -> 401; valid header but disallowed role -> 403.
"""
from functools import wraps

from flask import g, request

from common import VALID_ROLES
from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_error,
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or invalid X-User-ID / X-User-Role header",
        )
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce that g.user_role is allowed."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise_error(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    f"Role {g.user_role} not permitted for this operation",
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator
