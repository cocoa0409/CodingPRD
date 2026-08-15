"""Auth middleware: X-User-ID + X-User-Role header validation and RBAC."""

from flask import request
from errors import err, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_INSUFFICIENT_PERMISSIONS

VALID_ROLES = {
    "ComplianceAnalyst",
    "LegalCounsel",
    "EngineeringManager",
    "SecurityAnalyst",
    "ReleaseManager",
    "CISO",
    "PlatformAdmin",
}


def get_auth():
    """Validate auth headers. Returns (user_id, role). Raises on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID or X-User-Role header is missing or invalid")
    if not role or role not in VALID_ROLES:
        raise err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID or X-User-Role header is missing or invalid")
    return user_id.strip(), role


def require_roles(*allowed):
    """Validate auth and ensure the role is in allowed set."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err(ERR_INSUFFICIENT_PERMISSIONS,
                  "Current role does not have permission for this operation")
    return user_id, role


def get_json_body():
    """Parse JSON body; malformed -> ERR_INVALID_REQUEST. Empty body -> {}."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "General request format error")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "General request format error")
    return body
