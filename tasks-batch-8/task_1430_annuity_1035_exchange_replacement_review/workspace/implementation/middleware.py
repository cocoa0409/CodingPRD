"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.4 priority 1-2)."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

DECLARED_ROLES = {
    "CarrierAdmin",
    "Producer",
    "SuitabilityReviewer",
    "Principal",
    "ComplianceOfficer",
    "OperationsDesk",
}


def get_auth():
    """Extract X-User-ID and X-User-Role. Raises ApiError when missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing, empty, or an undeclared role",
            400,
        )
    if role not in DECLARED_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header missing, empty, or an undeclared role",
            400,
        )
    return user_id, role


def require_roles(*allowed_roles):
    """Validate auth headers and role authorization. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Caller role not in the endpoint's roles list",
            403,
        )
    return user_id, role
