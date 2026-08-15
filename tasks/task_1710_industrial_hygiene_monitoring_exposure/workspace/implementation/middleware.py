"""Auth header extraction and role checking (PRD section 2.1 / 2.8 stages 1-2)."""

from flask import request

from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_error,
)

ROLES = [
    "FirmAdmin",
    "IndustrialHygienist",
    "CIHDirector",
    "FieldTechnician",
    "LabAnalyst",
    "SiteSafetyManager",
    "Employee",
]

ALL_ROLES = tuple(ROLES)


def require_auth(allowed_roles):
    """Validate X-User-ID / X-User-Role headers, then endpoint role membership.

    Stage 1: both headers present and non-empty, else
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
    Stage 2: the declared role must be listed for the endpoint, else
    ERR_INSUFFICIENT_PERMISSIONS (403). An unrecognized role string passes
    stage 1 (it is non-empty) and fails stage 2.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or not user_id.strip() or not role.strip():
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in allowed_roles:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role not permitted for this endpoint",
        )
    return user_id, role
