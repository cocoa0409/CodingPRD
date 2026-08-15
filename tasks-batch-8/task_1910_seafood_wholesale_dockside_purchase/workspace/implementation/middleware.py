"""Auth header extraction and role gating (PRD section 2.1)."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = {
    "OperationsManager",
    "DockBuyer",
    "VesselAgent",
    "GradingInspector",
    "InventoryPlanner",
    "LogisticsCoordinator",
    "ComplianceOfficer",
    "Customer",
    "Any",
}


def auth():
    """Return (user_id, role). Missing headers / undeclared role -> 400."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and the role must be declared",
        )
    return uid, role


def require(role, allowed):
    """Role must be permitted for the endpoint, else 403."""
    if role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role %s is not permitted for this endpoint" % role,
        )
