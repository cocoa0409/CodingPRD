"""Auth header extraction and RBAC (PRD §2.1 / SCAFFOLD §1.7).

Headers: X-User-ID (acting operator), X-User-Role (one of five roles).
Validation order: authentication (401) is always checked before authorization
(403), per PRD §2.8.
"""
from functools import wraps

from flask import request

from errors import err

ROLES = {"Sponsor", "IRBReviewer", "CoordinatorStaff", "Investigator", "SafetyOfficer"}


def get_identity():
    """Return (user_id, role), raising ERR_UNAUTHENTICATED (401) if either
    header is missing or the role is not a recognized role (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require(*allowed_roles):
    """Decorator: authenticate, then authorize the role against the allowed set.

    Injects the authenticated (user_id, role) as kwargs `caller_id` / `caller_role`.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()
            if role not in allowed:
                err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % role)
            kwargs["caller_id"] = user_id
            kwargs["caller_role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
