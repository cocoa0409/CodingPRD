"""Auth header extraction and RBAC checks (PRD §2.1, §2.7)."""
from flask import request

from errors import err

RECOGNIZED_ROLES = {
    "RecallCoordinator",
    "QualityOfficer",
    "FieldServiceAgent",
    "FinanceClerk",
    "PlatformAdmin",
}


def authenticate():
    """Validate X-User-Role; return (user_id, role). Raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in RECOGNIZED_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-Role header")
    return user_id, role


def authorize(role, allowed_roles):
    """Raise ERR_FORBIDDEN_ROLE if role not in allowed_roles."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
