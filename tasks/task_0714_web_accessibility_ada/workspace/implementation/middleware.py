"""Auth header extraction and role checking."""
from flask import request
from errors import err

KNOWN_ROLES = {"PlatformAdmin", "OrgAdmin", "AuditEngineer", "RemediationVendor", "ComplianceManager"}


def authenticate():
    """Validate X-User-ID and X-User-Role. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED if either header missing or role unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed_roles):
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
