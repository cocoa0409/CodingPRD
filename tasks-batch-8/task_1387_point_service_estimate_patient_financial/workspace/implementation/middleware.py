"""Auth: X-User-ID / X-User-Role extraction, role authorization (PRD 2.1)."""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_MISSING_CONTEXT,
)

ROLES = {
    "Registrar",
    "FinancialCounselor",
    "UtilizationReviewer",
    "ClearanceSupervisor",
    "SystemAdmin",
}

ALL_ROLES = sorted(ROLES)


def authenticate(allowed_roles):
    """Priority 1 (headers) then priority 2 (role membership).

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is not None:
        user_id = user_id.strip()
    if role is not None:
        role = role.strip()
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_CONTEXT,
            "X-User-ID and X-User-Role headers must be present and non-empty, "
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
