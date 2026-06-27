"""Auth header extraction and role checking (PRD §2.1)."""
from functools import wraps
from flask import request, g

import errors
from errors import err

VALID_ROLES = {
    "HerdManager",
    "ParlorTech",
    "Veterinarian",
    "CoopSettlementAgent",
    "Auditor",
}


def extract_user_context():
    """Validate the two mandatory auth headers (PRD §2.1).

    X-User-ID identifies the acting user; X-User-Role declares the role. If
    either header is missing or malformed -> ERR_MISSING_OR_INVALID_USER_CONTEXT.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                  "Missing or invalid X-User-ID / X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                  "Missing or invalid X-User-ID / X-User-Role")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: enforce auth (priority 1) then RBAC (priority 2)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = extract_user_context()
            if role not in allowed_roles:
                raise err(errors.ERR_INSUFFICIENT_PERMISSIONS,
                          "Role %s is not permitted for this operation" % role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
