"""Auth header extraction and RBAC (PRD 2.1 / SCAFFOLD validations priority 1-2).

Mandatory headers: X-User-ID, X-User-Role. Roles: FacilityManager, FrontDesk,
Member, Instructor. Missing/unknown -> ERR_UNAUTHENTICATED (401).
Role not permitted for operation -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"FacilityManager", "FrontDesk", "Member", "Instructor"}


def authenticate():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers")
    return user_id, role


def require_role(role, allowed_roles):
    """Priority 2: role must be permitted for this operation."""
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role '%s' is not permitted for this operation" % role)
