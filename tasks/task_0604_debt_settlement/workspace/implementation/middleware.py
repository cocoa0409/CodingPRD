"""Auth header extraction and RBAC (PRD §2.1)."""
from functools import wraps

from flask import request, g

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    fail,
)

ROLES = {"ProgramAdmin", "NegotiationAgent", "Client"}


def authenticate():
    """Extract and validate X-User-ID and X-User-Role headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce role membership."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                fail(ERR_FORBIDDEN, "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return deco
