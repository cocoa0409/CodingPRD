"""Auth header extraction and role checks (PRD §2.1).

Two mandatory headers: X-User-ID and X-User-Role. Roles are exactly 'Manager'
and 'Worker'. Missing/malformed -> ERR_UNAUTHENTICATED (401). Role not permitted
-> ERR_UNAUTHORIZED (403).
"""
from flask import request

from errors import ApiError

ROLE_MANAGER = "Manager"
ROLE_WORKER = "Worker"
VALID_ROLES = {ROLE_MANAGER, ROLE_WORKER}


def authenticate():
    """Validate the two headers are present and well-formed. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id.strip() == "" or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require_role(role, allowed):
    """allowed: iterable of role names permitted for the endpoint."""
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
