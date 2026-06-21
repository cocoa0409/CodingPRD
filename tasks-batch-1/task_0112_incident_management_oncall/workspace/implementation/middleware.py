"""Auth header extraction, RBAC, and shared request helpers (PRD 2.1, 2.8)."""
from flask import request

from errors import ApiError

VALID_ROLES = {"PlatformAdmin", "IncidentCommander", "ResponderUser"}


def require_user_context():
    """Priority 1: X-User-ID and X-User-Role present, role recognized.

    Returns (user_id, role) or raises ERR_MISSING_OR_INVALID_USER_CONTEXT.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            "Missing or invalid X-User-ID / X-User-Role.",
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2: acting role must be permitted for this operation."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")


def get_json_body():
    """Parse JSON body; tolerate empty body for action endpoints."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def get_pagination():
    """limit default 10, min 1, max 100; offset default 0, min 0.

    Malformed numeric params -> ERR_INVALID_REQUEST.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset
