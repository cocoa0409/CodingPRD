"""Auth header extraction and RBAC (PRD §2.1).

Headers: X-User-ID (acting user id), X-User-Role (one of four roles).
Validation priority: auth (401) -> role (403) -> existence (404) -> ownership (403).
"""
from flask import request

from errors import ApiError

ROLES = {"FarmManager", "Visitor", "GroupLeader", "GateAgent"}


def get_identity():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if either header is
    missing/blank, or ERR_FORBIDDEN_ROLE if the role is not a recognized role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        # An unrecognized role value cannot be permitted for any operation.
        raise ApiError("ERR_FORBIDDEN_ROLE", f"Unknown role: {role}")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", f"Role {role} not permitted for this operation")
