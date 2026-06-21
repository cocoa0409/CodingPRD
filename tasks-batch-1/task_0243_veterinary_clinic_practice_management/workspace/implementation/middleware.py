"""Auth header extraction + role checking (PRD §2.1, §1.4 priority 1-2)."""
from flask import request

import errors

KNOWN_ROLES = {"Receptionist", "Veterinarian", "PracticeManager"}


def get_role():
    """Validate the mandatory user-context headers (PRD §2.1).

    Both X-User-ID and X-User-Role must be present and the role must be one of
    the three known roles, else ERR_MISSING_OR_INVALID_USER_CONTEXT (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        errors.raise_err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                         "Missing or invalid user context headers.")
    return role


def require_roles(role, allowed):
    """ERR_FORBIDDEN_ROLE (403) when role is well-formed but not permitted."""
    if role not in allowed:
        errors.raise_err(errors.ERR_FORBIDDEN_ROLE,
                         "Role not permitted for this operation.")
