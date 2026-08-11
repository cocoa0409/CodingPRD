"""Auth header extraction and role checking."""

from flask import request

from errors import err_forbidden, err_missing_context

DECLARED_ROLES = {
    "IntakeCoordinator",
    "DamageInvestigator",
    "ClaimsAdjuster",
    "RecoveryManager",
    "Excavator",
    "Locator",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Raises on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise err_missing_context()
    return user_id, role


def require_roles(*roles):
    """Validate headers and role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in roles:
        raise err_forbidden()
    return user_id, role
