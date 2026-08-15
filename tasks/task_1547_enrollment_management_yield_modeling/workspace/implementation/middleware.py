"""Auth header extraction and role checking."""
from flask import request

from errors import (
    ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN,
)

ROLES = {
    "SystemAdmin",
    "EnrollmentManager",
    "AdmissionsOfficer",
    "ApplicationReader",
    "FinancialAidOfficer",
    "Applicant",
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, f"Role {role} not permitted for this endpoint")
    return user_id, role
