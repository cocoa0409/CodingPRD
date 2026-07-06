"""Auth header extraction and RBAC enforcement."""
from flask import request

from errors import ApiError

KNOWN_ROLES = {"PlatformAdmin", "EngagementLead", "SocAnalyst", "Auditor", "ClientContact"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role not permitted for this operation.")
