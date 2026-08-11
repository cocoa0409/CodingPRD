"""Auth middleware per PRD §2.1 and SCAFFOLD validations priority 1-3."""

from flask import request

from errors import err_unauthenticated, err_unauthorized_role

ROLES = {
    "Anonymous",
    "Resident",
    "Driver",
    "FieldInspector",
    "RouteSupervisor",
    "BillingClerk",
    "ProgramAdmin",
    "OutreachCoordinator",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing/unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Validate auth + role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_unauthorized_role()
    return user_id, role
