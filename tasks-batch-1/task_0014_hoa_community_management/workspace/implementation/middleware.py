"""Auth + RBAC: headers X-User-ID and X-User-Role per PRD §2.1."""
from __future__ import annotations

from functools import wraps

from flask import g, request

from errors import (
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    raise_err,
)


RECOGNIZED_ROLES = {
    "PlatformAdmin",
    "BoardPresident",
    "BoardSecretary",
    "Treasurer",
    "ACCMember",
    "HomeOwner",
}


def auth_required(allowed_roles=None):
    """Decorator: ensures X-User-ID + X-User-Role present + role allowed.

    Validation order (per PRD §2.11):
      1. headers present  -> ERR_UNAUTHENTICATED
      2. role recognized  -> ERR_UNAUTHORIZED
      3. role in allowed  -> ERR_UNAUTHORIZED
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role:
                raise_err(ERR_UNAUTHENTICATED,
                          "Missing X-User-ID or X-User-Role header")
            if user_role not in RECOGNIZED_ROLES:
                raise_err(ERR_UNAUTHORIZED, f"Unknown role: {user_role}")
            if allowed_roles is not None and user_role not in allowed_roles:
                raise_err(ERR_UNAUTHORIZED,
                          f"Role {user_role} not permitted for this endpoint")
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
