"""Auth middleware and role-checking per PRD section 2.1."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

VALID_ROLES = {
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
    "ClaimantRole",
}


def get_auth():
    """Extract and validate X-User-ID and X-User-Role headers.

    Returns (user_id, role) tuple on success.
    Raises ApiError on failure.
    """
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()

    if not user_id or not role:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required",
            400,
        )

    if role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role must be one of the six recognized roles",
            400,
        )

    return user_id, role


def require_role(*allowed_roles):
    """Check that the caller's role is in the allowed set.

    Returns (user_id, role) on success.
    Raises ApiError with ERR_INSUFFICIENT_PERMISSIONS on failure.
    """
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role %s is not permitted to invoke this endpoint" % role,
            403,
        )
    return user_id, role
