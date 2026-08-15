"""Auth middleware (PRD section 2.1): X-User-ID / X-User-Role validation and
per-endpoint role authorization."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ROLES = {
    "PlanAdministrator",
    "IndependentFiduciary",
    "Recordkeeper",
    "Participant",
}

ALL_ROLES = [
    "PlanAdministrator",
    "IndependentFiduciary",
    "Recordkeeper",
    "Participant",
]


def authenticate(allowed_roles):
    """Validation cascade priorities 1 (headers) then 2 (role authorization).
    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not user_id.strip()
        or role is None
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and "
            "X-User-Role must name one of the declared roles",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role
