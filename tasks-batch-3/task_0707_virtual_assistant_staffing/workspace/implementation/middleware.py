"""Auth header extraction + RBAC primitives (PRD §2.1).

Headers (§2.1): X-User-ID identifies the caller, X-User-Role names the role.
Role must be exactly one of StaffingManager | Client | VA, else ERR_UNAUTHENTICATED.
"""
from flask import request

from errors import err

ROLES = {"StaffingManager", "Client", "VA"}


def auth():
    """Validate X-User-Role (priority 1). Returns (role, user_id).

    Missing or unrecognized role -> ERR_UNAUTHENTICATED (401).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "X-User-Role missing or unrecognized")
    return role, user_id


def require_role(role, allowed):
    """Authorization (priority 2): role must be in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
