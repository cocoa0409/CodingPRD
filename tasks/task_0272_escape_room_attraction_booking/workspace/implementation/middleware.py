"""Auth header extraction, RBAC role checks, and shared request helpers."""
from flask import request

import errors
from errors import err

ROLES = {"PlatformAdmin", "VenueManager", "GameMaster", "Customer"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when either header
    is missing/blank (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    return user_id, role


def require_roles(allowed):
    """Authenticate then enforce that the caller's role is in `allowed`.
    Returns (user_id, role)."""
    user_id, role = get_identity()
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
    return user_id, role


def get_json():
    """Parse JSON body; tolerate empty body as {}."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data
