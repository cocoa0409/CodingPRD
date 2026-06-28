"""Auth header extraction and RBAC enforcement (PRD §2.1, §3.8)."""
from flask import request

from errors import err

ROLES = {"ContractingOfficer", "Vendor", "Auditor"}


def get_identity():
    """Validate the mandatory identity headers. Raises ERR_UNAUTHENTICATED.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid identity headers.")
    return user_id, role


def require_role(role, allowed):
    """Authorization check (priority 2). Raises ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")


def auth(allowed_roles):
    """Run auth (priority 1) + authorization (priority 2); return (user_id, role)."""
    user_id, role = get_identity()
    require_role(role, allowed_roles)
    return user_id, role
