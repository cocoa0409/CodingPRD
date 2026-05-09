"""Auth middleware (PRD §2.1)."""
from flask import request

from errors import api_error

VALID_ROLES = {
    "HousingDirector",
    "HousingOfficer",
    "Applicant",
    "Citizen",
    "IntegrationGateway",
}


def get_auth():
    """Validate X-User-ID / X-User-Role headers and return (user_id, role).

    Per PRD §2.1, missing or invalid header => ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role:
        raise api_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required",
        )
    if role not in VALID_ROLES:
        raise api_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            f"Unknown role: {role}",
        )
    return user_id, role


def require_roles(*allowed):
    """Validate auth, then enforce role membership."""
    user_id, role = get_auth()
    if role not in allowed:
        raise api_error(
            "ERR_INSUFFICIENT_PERMISSIONS",
            f"Role {role} is not permitted to perform this operation",
        )
    return user_id, role
