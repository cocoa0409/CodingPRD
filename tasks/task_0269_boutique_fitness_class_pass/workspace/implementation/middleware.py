"""Auth header extraction and RBAC helpers (§2.1, §1.4 priorities 1-2)."""

from flask import request

from errors import err

ROLES = {"NetworkAdmin", "StudioManager", "Member"}


def get_principal():
    """Validate auth headers (§2.1).

    Both X-User-ID and X-User-Role must be present, and the role must be one of
    the three recognised values. Otherwise ERR_UNAUTHENTICATED (401).
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized authentication headers")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN (403) when the acting role is not in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
