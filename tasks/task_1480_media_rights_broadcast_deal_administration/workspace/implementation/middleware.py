"""Auth middleware: X-User-ID / X-User-Role headers and role checking (PRD §2.1)."""
from flask import request

from errors import raise_error

VALID_ROLES = {
    "RightsManager",
    "BidCoordinator",
    "FinanceController",
    "ProductionAuditor",
    "ComplianceOfficer",
}

ALL_ROLES = VALID_ROLES


def get_auth():
    """Validate the identity headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise_error("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in VALID_ROLES:
        raise_error("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return user_id, role


def require_roles(allowed_roles):
    """Check headers then role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise_error("ERR_INSUFFICIENT_PERMISSIONS")
    return user_id, role
