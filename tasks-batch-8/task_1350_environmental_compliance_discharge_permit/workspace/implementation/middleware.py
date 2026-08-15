"""Auth header extraction and role checking."""

from flask import request

from errors import (
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = {
    "EnvironmentalManager",
    "FieldSampler",
    "LabAnalyst",
    "LabValidator",
    "ComplianceOfficer",
    "FacilityInspector",
    "Regulator",
    "SystemAdmin",
}


def get_caller():
    """Validate X-User-ID and X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID header missing or empty",
        )
    if not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role header missing or not a recognized role",
        )
    return user_id, role


def require_roles(allowed):
    """Check the caller's role against the endpoint's allowed roles.

    `allowed` is a list of role names, or ["Any"] to mean any authenticated role.
    """
    user_id, role = get_caller()
    if "Any" in allowed:
        return user_id, role
    if role not in allowed:
        raise err(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            f"Role {role} is not permitted for this operation",
        )
    return user_id, role
