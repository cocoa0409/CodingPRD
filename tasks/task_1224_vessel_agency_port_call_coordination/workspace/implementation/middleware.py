"""Auth header extraction and role authorization (PRD section 2.1/2.7)."""
from flask import request

from errors import ApiError

ROLES = {
    "AgencyAdmin",
    "AgencyOps",
    "AgencyFinance",
    "PortAuthority",
    "PrincipalRep",
    "VendorRep",
    "CrewingAgent",
    "HusbandryOfficer",
}

ANY_ROLE = sorted(ROLES)


def get_auth():
    """Stage 1: headers present and role declared, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be declared",
            401,
        )
    return user_id, role


def require_roles(allowed):
    """Stages 1+2: authentication then role authorization."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not authorized for this endpoint" % role,
            403,
        )
    return user_id, role
