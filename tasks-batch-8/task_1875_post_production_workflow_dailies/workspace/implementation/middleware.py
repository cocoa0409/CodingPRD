"""Auth header extraction and role checking (PRD §2.1, §2.9 steps 1-2)."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PostSupervisor",
    "MediaManager",
    "DailiesCoordinator",
    "ConformEditor",
    "ReviewerLead",
    "QCOperator",
    "FacilityAdmin",
    "VendorRep",
    "Artist",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED when either header
    is missing or the role value is not one of the nine declared roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or unrecognized X-User-Role / X-User-ID headers",
            401,
        )
    if role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or unrecognized X-User-Role / X-User-ID headers",
            401,
        )
    return user_id, role


def require_roles(allowed_roles):
    """Validate authentication and enforce role authorization.

    Returns (user_id, role) on success.
    """
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN,
            "Role not permitted for this endpoint",
            403,
        )
    return user_id, role
