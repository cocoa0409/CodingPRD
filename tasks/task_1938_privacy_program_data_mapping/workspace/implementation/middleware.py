"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from errors import ApiError

ROLES = {
    "PrivacyAdmin",
    "DataSteward",
    "BusinessOwner",
    "LegalCounsel",
    "VendorManager",
    "Consumer",
}

# The five staff roles that share all standard GET endpoints.
STAFF_ROLES = (
    "PrivacyAdmin",
    "DataSteward",
    "LegalCounsel",
    "VendorManager",
    "BusinessOwner",
)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return uid, role


def require_roles(*roles):
    uid, role = authenticate()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Caller role is not authorized for this endpoint")
    return uid, role


def get_body():
    """Parse the JSON request body. Absent body -> {}. Non-object -> 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data
