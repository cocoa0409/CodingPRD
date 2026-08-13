"""Auth middleware: extract X-User-ID and X-User-Role."""

from flask import request

from errors import unauthenticated, unauthorized_role

VALID_ROLES = {
    "OpsController",
    "AirfieldInspector",
    "MaintenanceLead",
    "AirlineCoordinator",
    "SystemAdmin",
}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise unauthenticated()
    if not role or role not in VALID_ROLES:
        # Malformed role header -> unauthenticated
        raise unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Ensure caller role is in roles."""
    user_id, role = get_auth()
    if role not in roles:
        raise unauthorized_role()
    return user_id, role
