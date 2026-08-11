"""Auth middleware per PRD §2.1 and validation priorities 1-2.

Headers: X-User-ID, X-User-Role.
Roles: CourtAdmin, Attorney, CourtClerk, ParalegalStaff.
"""
from flask import request

from errors import ApiError

ROLES = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_auth():
    """Validate auth headers (priority 1). Returns AuthContext."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Missing or malformed X-User-Role / X-User-ID", 401)
    return AuthContext(user_id, role)


def require_roles(auth, allowed):
    """Validate RBAC (priority 2)."""
    if auth.role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Role not permitted to invoke this endpoint", 403)
