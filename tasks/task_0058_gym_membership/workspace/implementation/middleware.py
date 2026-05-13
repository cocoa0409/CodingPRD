"""Auth/RBAC middleware."""
from flask import request, g
from errors import raise_err


VALID_ROLES = {"PlatformAdmin", "StaffOps", "Member", "Trainer", "system"}


def extract_auth():
    """Extract X-User-ID and X-User-Role; validate presence and role recognition.

    Raises ERR_AUTH_REQUIRED if missing or unknown role.
    Stores values on flask.g for handlers to read.
    """
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_err("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise_err("ERR_AUTH_REQUIRED", f"Unknown role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles):
    """Check that the caller's role is one of the allowed."""
    if g.user_role not in roles:
        raise_err("ERR_FORBIDDEN", f"Role {g.user_role} not permitted")


def is_role(*roles) -> bool:
    return getattr(g, "user_role", None) in roles
