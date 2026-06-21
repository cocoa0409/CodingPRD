"""Auth context extraction and RBAC (PRD §2.1, §2.6)."""
from flask import request

import errors

VALID_ROLES = {"FrameDesigner", "FrameProductionTech", "FrontDeskClerk", "Customer"}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_auth():
    """Priority 1: auth headers present and well-formed.

    Both X-User-ID and X-User-Role must be present, non-empty, and the role
    must be one of the four recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        errors.raise_err(errors.ERR_MISSING_AUTH_CONTEXT, "Missing authentication headers")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        errors.raise_err(errors.ERR_MISSING_AUTH_CONTEXT, "Empty authentication headers")
    if role not in VALID_ROLES:
        errors.raise_err(errors.ERR_MISSING_AUTH_CONTEXT, "Unrecognized role")
    return AuthContext(user_id, role)


def require_role(auth, allowed_roles):
    """Priority 2: authorization. Role must be permitted for the operation."""
    if auth.role not in allowed_roles:
        errors.raise_err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
