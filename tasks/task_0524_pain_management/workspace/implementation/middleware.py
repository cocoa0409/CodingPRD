from flask import request

import errors

VALID_ROLES = {
    "ClinicAdmin",
    "IntakeCoordinator",
    "Prescriber",
    "ComplianceOfficer",
    "PriorAuthClerk",
}


def get_user_context():
    """Extract and validate X-User-ID / X-User-Role. Raises on missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    return user_id, user_role


def require_role(allowed_roles):
    """Validate auth headers then enforce role membership.

    Returns (user_id, user_role). Raises ApiError with the correct priority
    ordering: missing/invalid header (400) before insufficient permission (403).
    """
    user_id, user_role = get_user_context()
    if user_role not in allowed_roles:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_PERMISSIONS, 403,
            "Role not permitted for this operation",
        )
    return user_id, user_role
