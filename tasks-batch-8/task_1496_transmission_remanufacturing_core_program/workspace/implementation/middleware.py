"""Auth header extraction and role checking per scaffold §1.4 priorities 1-2."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

# Roles that exist in the system (PRD §2.1). Any authenticated caller may use
# GET endpoints ("Any"); write endpoints list explicit roles.
ROLES = {
    "ProgramAdmin",
    "InventoryPlanner",
    "RemanPlanner",
    "RemanTechnician",
    "Calibrator",
    "DynoOperator",
    "CoreIntakeClerk",
    "CoreInspector",
    "Installer",
    "WarrantyAdjuster",
    "Any",
}


def get_auth():
    """Validate auth headers; return (user_id, role).

    Priority 1: headers present and non-empty.
    Priority 2: role permitted for this endpoint.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty",
            400,
        )
    return user_id, role


def require_role(allowed_roles):
    """Priority 2 check. `allowed_roles` is a collection of role names;
    the literal string "Any" means any authenticated role may call."""
    user_id, role = get_auth()
    if "Any" in allowed_roles:
        return user_id, role
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this endpoint",
            403,
        )
    return user_id, role
