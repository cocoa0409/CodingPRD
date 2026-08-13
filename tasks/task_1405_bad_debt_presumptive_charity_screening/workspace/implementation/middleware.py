"""Auth: X-User-ID / X-User-Role extraction, role authorization (PRD 2.1).

Validation priority (PRD 2.9): (1) headers present and well-formed ->
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400); (2) role membership in the
endpoint's authorized role list -> ERR_INSUFFICIENT_PERMISSIONS (403).
"""

from flask import request

from errors import ApiError, ERR_FORBIDDEN, ERR_MISSING_CONTEXT

ROLES = {
    "Collector",
    "FinancialCounselor",
    "RevenueIntegrityOfficer",
    "CollectionAgencyUser",
}

ROLE_COLLECTOR = "Collector"
ROLE_COUNSELOR = "FinancialCounselor"
ROLE_OFFICER = "RevenueIntegrityOfficer"
ROLE_AGENCY = "CollectionAgencyUser"

ALL_ROLES = sorted(ROLES)


def authenticate(allowed_roles):
    """Returns (user_id, role). X-User-ID is an opaque operator identifier;
    it is never compared against any resource id, only stamped for
    attribution / segregation-of-duties comparisons."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is not None:
        user_id = user_id.strip()
    if role is not None:
        role = role.strip()
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_CONTEXT,
            "X-User-ID and X-User-Role headers must be present and well-formed, "
            "and X-User-Role must be a declared role",
            400,
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN,
            "role %s is not authorized for this endpoint" % role,
            403,
        )
    return user_id, role
