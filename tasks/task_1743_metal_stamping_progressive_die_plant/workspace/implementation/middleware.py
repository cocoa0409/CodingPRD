"""Auth middleware: header extraction and role checking per PRD §2.1."""
from flask import request

from errors import unauthenticated, unauthorized

ROLES = {
    "PlantAdmin",
    "ProcessEngineer",
    "ToolroomManager",
    "SetupLead",
    "ProductionPlanner",
    "PressOperator",
    "QualityEngineer",
    "ShippingClerk",
    "CostAnalyst",
}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if headers missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require_role(*allowed):
    """Authenticate then authorize against the allowed role set."""
    user_id, role = get_auth()
    if role not in allowed:
        raise unauthorized()
    return user_id, role
