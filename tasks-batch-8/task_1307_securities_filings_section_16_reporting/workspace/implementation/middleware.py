"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

from errors import (
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
    ApiError,
)

ALL_ROLES = {
    "ComplianceOfficer",
    "FilingCoordinator",
    "FilingAgent",
    "EquityPlanAdmin",
    "ReportingInsider",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role headers."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and non-empty.",
            400,
        )
    if role not in ALL_ROLES:
        raise ApiError(ERR_FORBIDDEN_ROLE, f"Unknown role: {role}", 403)
    return user_id, role


def require_role(*allowed):
    """Return (user_id, role) if the caller's role is in `allowed`."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_ROLE, f"Role {role} not permitted.", 403)
    return user_id, role
