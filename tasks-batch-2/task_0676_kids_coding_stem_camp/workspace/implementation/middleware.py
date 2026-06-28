"""Auth header extraction and RBAC (PRD §2.1, §2.10; SCAFFOLD §1.4, §1.7)."""
from flask import request

import errors
from errors import err

ROLES = {"CenterAdmin", "Instructor", "Guardian"}


def get_auth():
    """Priority 1 (auth): X-User-Role and X-User-ID present, role known.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Priority 2 (auth): acting role permitted for this operation."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation." % role)
