"""Auth header extraction, role checking, and pagination parsing."""
from flask import request
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

KNOWN_ROLES = {
    "PlatformAdmin",
    "OpsDispatcher",
    "CrewLead",
    "Subcontractor",
    "ClientContact",
    "ClaimsAdjuster",
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header", 401)
    if role not in KNOWN_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, f"Unknown role: {role}", 401)
    return user_id, role


def require_roles(*allowed_roles):
    """Check that the caller's role is in the allowed list."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, f"Role {role} not authorized for this endpoint", 403)
    return user_id, role


def get_pagination():
    """Parse limit/offset from query params with defaults."""
    try:
        limit = int(request.args.get("limit", "10"))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def get_json_body():
    """Get JSON body, returning empty dict if none."""
    if request.content_type and "json" in request.content_type:
        return request.get_json(silent=True) or {}
    return request.get_json(silent=True) or {}
