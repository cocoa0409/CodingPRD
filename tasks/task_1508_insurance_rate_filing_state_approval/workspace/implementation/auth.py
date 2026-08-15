"""Auth middleware (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The six recognized roles
are PlatformAdmin, ProductActuary, FilingAnalyst, ComplianceOfficer,
StateRegulator, ImplementationLead. Missing/malformed headers ->
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400); a recognized role that is
not authorized for the operation -> ERR_FORBIDDEN_FOR_ROLE (403).
"""
from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = {
    "PlatformAdmin",
    "ProductActuary",
    "FilingAnalyst",
    "ComplianceOfficer",
    "StateRegulator",
    "ImplementationLead",
}

ALL_ROLES = ROLES  # read-only endpoints are open to all six roles


def authenticate(allowed_roles):
    """Validate identity headers and role authorization.

    Returns (user_id, role). Raises ApiError on failure, in the §2.8 order:
    header well-formedness first, then role authorization.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not user_id.strip()
        or role is None
        or not role.strip()
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and well-formed",
            400,
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Caller role not permitted on this endpoint",
            403,
        )
    return user_id.strip(), role
