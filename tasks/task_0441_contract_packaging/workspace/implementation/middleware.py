"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.7).

Every request must carry X-User-ID and X-User-Role. The three known roles are
Receiver, Scheduler, QAInspector. Missing either header, or an unknown role,
-> ERR_UNAUTHENTICATED (401). A recognized but unpermitted role ->
ERR_UNAUTHORIZED (403). X-User-ID is opaque and never compared to any entity id.
"""
from functools import wraps

from flask import request

import errors

KNOWN_ROLES = {"Receiver", "Scheduler", "QAInspector"}
ALL_ROLES = ("Receiver", "Scheduler", "QAInspector")


def authenticate():
    """Validate auth headers. Returns the role string or raises ApiError.

    Priority 1 (auth): X-User-Role and X-User-ID present and role is known.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return role


def require_role(*allowed_roles):
    """Decorator: authenticate (401) then authorize (403) against allowed_roles.

    Order matches validation priorities 1 then 2.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = authenticate()  # priority 1
            if role not in allowed:  # priority 2
                raise errors.unauthorized()
            return fn(*args, **kwargs)
        return wrapper
    return decorator
