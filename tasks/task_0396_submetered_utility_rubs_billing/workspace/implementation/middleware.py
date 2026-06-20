"""Auth header extraction and role checks (PRD §2.1, §3.12)."""

from functools import wraps

from flask import request, g

from errors import ApiError

VALID_ROLES = {"PropertyManager", "MeterTech", "Tenant", "Auditor"}


def extract_user_context():
    """Validate the two mandatory auth headers (PRD §2.1).

    Both X-User-ID and X-User-Role must be present, non-empty, and the role
    must be one of the four recognized roles. Otherwise
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401).
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "Missing or invalid X-User-ID header")
    if not user_role or user_role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "Missing or invalid X-User-Role header")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(*allowed_roles):
    """Decorator: auth first, then role authorization (priority 1 then 2)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = extract_user_context()
            if user_role not in allowed_roles:
                raise ApiError("ERR_FORBIDDEN_FOR_ROLE",
                               "Role %s not permitted for this operation" % user_role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
