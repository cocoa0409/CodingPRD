"""Auth context extraction + RBAC (PRD §2.1, §1.7).

Every request must carry X-User-ID and X-User-Role (PRD §2.1). Roles are
exactly Creator | Patron | PlatformAdmin.
"""
from flask import request

import errors

ROLES = {"Creator", "Patron", "PlatformAdmin"}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_creator(self):
        return self.role == "Creator"

    @property
    def is_patron(self):
        return self.role == "Patron"

    @property
    def is_admin(self):
        return self.role == "PlatformAdmin"


def require_auth():
    """Priority 1: X-User-ID and X-User-Role present and well-formed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        errors.fail(errors.ERR_MISSING_AUTH_CONTEXT, "Missing X-User-ID header")
    if not role or role not in ROLES:
        errors.fail(errors.ERR_MISSING_AUTH_CONTEXT, "Missing or malformed X-User-Role header")
    return AuthContext(user_id.strip(), role)


def require_role(ctx, allowed_roles):
    """Priority 2: role is permitted for this operation (PRD §1.7)."""
    if ctx.role not in allowed_roles:
        errors.fail(errors.ERR_UNAUTHORIZED, "Role %s not permitted for this operation" % ctx.role)
