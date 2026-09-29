"""Auth header extraction and role admissibility (PRD 2.1, order steps 1-2)."""

from flask import request

from errors import ApiError

SYSTEM_ADMIN = "SystemAdmin"
RSO = "ResearchSecurityOfficer"
CRO = "ConflictReviewOfficial"
AGENCY_LIAISON = "AgencyLiaison"
INVESTIGATOR = "Investigator"

ALL_ROLES = (SYSTEM_ADMIN, RSO, CRO, AGENCY_LIAISON, INVESTIGATOR)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    return str(user_id).strip(), str(role).strip()


def require(*allowed):
    """Step 1 (headers) then step 2 (role admissibility)."""
    user_id, role = authenticate()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unknown role '%s'." % role)
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not perform this operation." % role)
    return user_id, role


def require_any():
    return require(*ALL_ROLES)
