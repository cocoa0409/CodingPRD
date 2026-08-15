"""Auth header extraction and role checking (PRD 2.1)."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

ROLES = {"Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"}


def auth(allowed_roles):
    """Validate X-User-ID / X-User-Role headers, then role authorization.
    Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID or X-User-Role header is missing or invalid",
            400,
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Current role does not have permission for this operation",
            403,
        )
    return uid, role
