"""Auth header extraction and role checking, per PRD §2.1 and SCAFFOLD §1.4."""
from flask import request

import errors


VALID_ROLES = {"ServiceManager", "PlantOperator", "Technician", "SafetyOfficer"}


class AuthContext:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def require_auth() -> AuthContext:
    """Priority 1: X-User-Role and X-User-ID headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated("X-User-Role is not a declared role")
    return AuthContext(user_id=user_id, role=role)


def require_role(ctx: AuthContext, allowed: set):
    """Priority 3: role is permitted for this endpoint."""
    if ctx.role not in allowed:
        raise errors.forbidden(f"Role {ctx.role} not permitted for this endpoint")
