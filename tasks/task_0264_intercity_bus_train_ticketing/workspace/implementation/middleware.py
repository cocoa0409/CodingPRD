"""Auth header extraction and RBAC (PRD 2.1, validations priority 1-2).

Headers: X-User-ID and X-User-Role. Missing either -> ERR_UNAUTHENTICATED.
Role not in the endpoint's allowed set -> ERR_FORBIDDEN_ROLE.
"""
from flask import request

from errors import err
from constants import ROLES


def get_identity():
    """Return (user_id, role) after enforcing presence (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Enforce the role is permitted for this operation (priority 2)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")


def auth(allowed_roles):
    """Run priority-1 auth then priority-2 RBAC; return (user_id, role)."""
    user_id, role = get_identity()
    require_role(role, allowed_roles)
    return user_id, role
