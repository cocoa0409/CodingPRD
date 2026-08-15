"""Auth header extraction and role authorization (PRD section 2.1)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = {
    "PlantOperator",
    "LabTechnician",
    "QualityManager",
    "QualityAgencyInspector",
    "ComplianceOfficer",
    "AccountsReceivable",
}

ALL_ROLES = [
    "PlantOperator",
    "LabTechnician",
    "QualityManager",
    "QualityAgencyInspector",
    "ComplianceOfficer",
    "AccountsReceivable",
]


def authenticate():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not isinstance(user_id, str)
        or not user_id.strip()
        or role is None
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and syntactically valid",
        )
    return user_id, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role {} is not permitted to call this endpoint".format(role),
        )
