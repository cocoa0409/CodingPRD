"""Auth header extraction and role checking."""

from flask import request
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLES = {
    "PlatformAdmin",
    "EngagementManager",
    "ClassificationAnalyst",
    "HRApprover",
    "LegalApprover",
    "ComplianceBoardMember",
    "ComplianceOfficer",
    "TaxReportingSpecialist",
    "AgencyLiaison",
}

# Any authenticated role may perform GETs.
ALL_ROLES = list(ROLES)


def require_auth(allowed_roles):
    """Validate X-User-Role / X-User-ID and role membership. Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not user_id:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or invalid X-User-Role or X-User-ID header")
    if role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, "Role not permitted for this endpoint")
    return user_id, role
