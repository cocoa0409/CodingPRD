"""Auth header extraction and role checking per PRD §2.1."""

from functools import wraps

from flask import g, request

from errors import auth_required, forbidden


VALID_ROLES = {
    "PlatformAdmin",
    "WaterAdmin",
    "Operator",
    "DeviceAgent",
    "Tenant",
}


def extract_auth():
    """Pull X-User-ID and X-User-Role from the request, raising on failure.

    Stores them on flask.g for downstream use.
    """
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise auth_required()
    if role not in VALID_ROLES:
        raise forbidden(f"Unknown role: {role}")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce that the authenticated role is in the allowed set.

    WaterAdmin hierarchically overrides Operator: any operation an Operator
    can perform, a WaterAdmin may also perform. So if Operator is allowed,
    WaterAdmin is implicitly also allowed.
    """
    allowed = set(roles)
    # PRD §2.1: "WaterAdmin role hierarchically overrides the Operator role"
    if "Operator" in allowed:
        allowed.add("WaterAdmin")

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in allowed:
                raise forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco
