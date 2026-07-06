"""Auth header extraction and RBAC helpers."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {
    "Customer",
    "InventoryManager",
    "ComplianceOfficer",
    "CorporateBuyer",
    "PlatformAdmin",
}


def auth():
    """Validate mandatory headers, return (user_id, role). Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
