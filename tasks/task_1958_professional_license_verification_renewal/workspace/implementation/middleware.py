"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = [
    "ComplianceAdmin",
    "ComplianceOfficer",
    "HRPartner",
    "Employee",
    "ExternalAuditor",
]

ALL_ROLES = list(ROLES)

# Roles allowed to call GET /licensing/reports/compliance-summary (not Employee).
SUMMARY_ROLES = ["ComplianceAdmin", "ComplianceOfficer", "HRPartner", "ExternalAuditor"]


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_UNAUTHORIZED_ROLE", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
