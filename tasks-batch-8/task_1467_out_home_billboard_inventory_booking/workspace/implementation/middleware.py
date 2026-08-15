"""Auth middleware (PRD 2.1): X-User-ID + X-User-Role headers."""
from flask import request

from errors import ApiError, err_insufficient

ROLES = {
    "PlatformAdmin",
    "InventoryManager",
    "SalesPlanner",
    "SalesManager",
    "ProductionCoordinator",
    "FieldInstaller",
    "OperationsAuditor",
    "ComplianceOfficer",
    "FinanceAnalyst",
}


def auth_context():
    """Family 1: header presence and recognized role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers are required and the "
                       "role must be recognized")
    return user_id, role


def require_roles(*roles):
    """Family 2: endpoint-level role authorization."""
    user_id, role = auth_context()
    if role not in roles:
        raise err_insufficient()
    return user_id, role


def require_transition_role(role, allowed):
    """Per-transition role gate (family 2, PRD 2.1)."""
    if role not in allowed:
        raise err_insufficient()
