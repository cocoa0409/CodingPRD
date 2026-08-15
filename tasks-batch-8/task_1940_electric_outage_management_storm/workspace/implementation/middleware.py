"""Auth header extraction and role checking.

Headers (per PRD 2.1): X-User-ID and X-User-Role must be present and non-empty,
else ERR_MISSING_OR_INVALID_CONTEXT_HEADER (400). A role not authorized for the
endpoint is rejected with ERR_FORBIDDEN_ROLE (403).
"""
from flask import request
from errors import raise_err, ERR_MISSING_OR_INVALID_CONTEXT_HEADER, ERR_FORBIDDEN_ROLE

ALL_ROLES = [
    "EmergencyDirector", "Dispatcher", "TelemetryGateway", "FieldCrewLead",
    "SystemOperator", "MutualAidCoordinator", "MaterialsManager",
    "ClaimsOfficer", "Regulator",
]


def get_context():
    """Return (user_id, role) after validating presence of both headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise_err(ERR_MISSING_OR_INVALID_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers must be present and non-empty")
    return user_id, role


def require_roles(allowed_roles):
    """Validate headers and that the role is among allowed_roles."""
    user_id, role = get_context()
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN_ROLE,
                  f"Role {role} is not authorized for this endpoint")
    return user_id, role
