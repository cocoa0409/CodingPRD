"""Auth context extraction and role checking (validation ladder rungs 1-2)."""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = ("CreditAnalyst", "ModelValidator", "ChiefCreditOfficer", "ExternalAuditor")
ALL_ROLES = list(ROLES)


def require_roles(allowed_roles):
    """Validate X-User-ID / X-User-Role headers and endpoint role permission.

    Returns (user_id, role) on success; raises ApiError otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and role must be a declared role",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            403,
            "Caller role is not permitted on this endpoint",
        )
    return user_id, role
