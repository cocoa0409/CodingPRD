"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

import errors

VALID_ROLES = {"PlatformAdmin", "Restaurant", "Customer", "Dasher", "Support"}


def get_user_context():
    """Read and validate X-User-ID / X-User-Role.

    Both headers must be present and X-User-Role must be one of the five
    recognized roles, else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    return user_id, role


def require_roles(role, allowed):
    """Enforce that the acting role is permitted, else ERR_UNAUTHORIZED_ROLE."""
    if role not in allowed:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE)
