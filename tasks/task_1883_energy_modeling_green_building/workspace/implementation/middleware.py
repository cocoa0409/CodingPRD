"""Auth header extraction and role checking (PRD section 2.1, ladder stages 1+3)."""
from flask import request

from errors import ApiError

ROLES = {
    "ProgramAdmin",
    "ProjectAdministrator",
    "EnergyModeler",
    "DocumentationSpecialist",
    "CommissioningAgent",
    "CertificationReviewer",
}


def auth_headers():
    """Stage 1: X-User-ID and X-User-Role must be present and non-empty.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return user_id, role


def require_role(role, allowed):
    """Stage 3: role permission per the RBAC matrix."""
    if role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this operation"
        )
