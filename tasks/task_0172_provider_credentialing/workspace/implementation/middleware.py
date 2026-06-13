"""Auth header extraction and RBAC enforcement."""
from flask import request

from errors import err

ROLES = {
    "SystemAdmin",
    "CredentialingSpecialist",
    "MedicalDirector",
    "PeerReviewer",
    "EnrollmentCoordinator",
    "ComplianceOfficer",
}


def require_auth():
    """Validate X-User-ID and X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT",
                  "Missing or invalid user context headers.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role is not permitted to perform this operation.")
