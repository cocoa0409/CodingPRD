"""Auth header extraction and RBAC (PRD §2.1 / SCAFFOLD §1.7).

Headers: X-User-ID (acting operator), X-User-Role (one of four roles).
"""
from functools import wraps

from flask import request

from errors import err

ROLES = {"Coordinator", "BackgroundScreener", "MatchSpecialist", "Supervisor"}


def get_identity():
    """Return (user_id, role), raising ERR_UNAUTHENTICATED if either header is
    missing or the role is not recognised (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require(*allowed_roles):
    """Decorator: authenticate, then authorise the role against the allowed set.

    Authentication (401) is always checked before authorisation (403), per the
    fixed validation ordering in PRD §2.6.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                err("ERR_UNAUTHORIZED", "Role %s is not permitted for this operation" % role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
