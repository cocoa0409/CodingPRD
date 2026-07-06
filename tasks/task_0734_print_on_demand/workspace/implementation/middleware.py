"""Auth/RBAC middleware. Priorities 1 & 2 per PRD §2.9."""
from functools import wraps

from flask import request, g

from errors import raise_error

VALID_ROLES = {"Anonymous", "Creator", "PlatformAdmin", "FulfillmentPartner"}


def _authenticate():
    """Priority 1: header presence and role recognition."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_error("ERR_UNAUTHENTICATED", "missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise_error("ERR_UNAUTHENTICATED", f"unknown role: {role}")
    g.user_id = user_id
    g.role = role


def authenticate_optional():
    """Register endpoint accepts no auth — treat missing headers as Anonymous.
    But if headers are present, they must still be well-formed roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id and role:
        if role not in VALID_ROLES:
            raise_error("ERR_UNAUTHENTICATED", f"unknown role: {role}")
        g.user_id = user_id
        g.role = role
    else:
        g.user_id = None
        g.role = "Anonymous"


def require_auth(allowed_roles):
    """Decorator: authenticate, then check role membership.

    `allowed_roles` — iterable of role names permitted for this endpoint.
    """
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.role not in allowed:
                raise_error("ERR_FORBIDDEN", f"role {g.role} not permitted")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def open_endpoint(allowed_roles):
    """Like require_auth but tolerates missing headers (register endpoint).
    Still checks role if headers are present."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate_optional()
            if g.role not in allowed:
                raise_error("ERR_FORBIDDEN", f"role {g.role} not permitted")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_role():
    return getattr(g, "role", None)


def current_user_id():
    return getattr(g, "user_id", None)
