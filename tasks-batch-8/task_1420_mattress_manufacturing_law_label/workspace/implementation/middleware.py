"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

import errors

ROLES = {
    "PlantManager",
    "ComplianceOfficer",
    "LineSupervisor",
    "QcInspector",
    "Retailer",
    "LogisticsCoordinator",
}

ALL_ROLES = [
    "PlantManager",
    "ComplianceOfficer",
    "LineSupervisor",
    "QcInspector",
    "Retailer",
    "LogisticsCoordinator",
]


def get_auth():
    """Tier 1: header presence and role validity."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or role not in ROLES:
        errors.raise_err(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
        )
    return user_id, role


def require_roles(allowed):
    """Tier 2: caller role must be in the endpoint's roles list."""
    user_id, role = get_auth()
    if role not in allowed:
        errors.raise_err(errors.ERR_FORBIDDEN_ROLE, "role not authorized for this endpoint")
    return user_id, role
