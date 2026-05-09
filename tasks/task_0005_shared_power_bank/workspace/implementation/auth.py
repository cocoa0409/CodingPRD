from flask import request
from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


VALID_ROLES = {"User", "Operator", "Partner", "Admin"}


def require_auth():
    """Priority 1: ensure both X-User-ID and X-User-Role headers are present."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Authentication required")
    return uid, role


def require_role(allowed: set[str]):
    """Priority 2: ensure caller's role is permitted for this endpoint."""
    uid, role = require_auth()
    if role not in allowed:
        raise APIError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")
    return uid, role


def get_identity():
    """Returns (uid, role) without enforcing presence (used for unauth endpoints)."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")
