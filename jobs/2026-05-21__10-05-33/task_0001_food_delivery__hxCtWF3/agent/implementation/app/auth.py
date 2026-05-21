"""Header parsing and RBAC. Identity binding per role."""
from flask import request, g

from .errors import fail

ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def parse_headers():
    """Pull X-User-ID and X-User-Role. ERR_AUTH_REQUIRED if missing/invalid role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise fail("ERR_AUTH_REQUIRED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_role(*allowed):
    """Raise ERR_FORBIDDEN unless the caller's role is in `allowed`."""
    role = g.get("user_role")
    if role not in allowed:
        raise fail("ERR_FORBIDDEN")


def role_id_is_entity() -> bool:
    """Customer/Restaurant/Rider bind X-User-ID to a real entity id."""
    return g.user_role in ("Customer", "Restaurant", "Rider")
