"""Auth header extraction and RBAC per PRD section 2.1."""

from flask import request

from errors import err

ROLES = {
    "OperatorAdmin",
    "SiteManager",
    "MaintenanceLead",
    "ComplianceInspector",
    "IntakeCoordinator",
    "Resident",
}

# Read endpoints are available to all roles.
ALL_ROLES = frozenset(ROLES)


def get_auth():
    """Validate X-User-ID and X-User-Role headers (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return user_id, role


def require_roles(*allowed):
    """Return (user_id, role) after checking header presence and role permission."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS")
    return user_id, role
