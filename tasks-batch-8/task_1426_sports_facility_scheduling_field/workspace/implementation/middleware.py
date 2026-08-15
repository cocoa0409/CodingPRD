"""Auth header extraction and role checking per PRD 2.1 / validations priority 1+3."""

from flask import request

import errors


ROLES = ("AthleticsAdmin", "FieldSupervisor", "OrgCoordinator", "FinanceClerk")

ANY_ROLE = ROLES


def get_auth():
    """Return (user_id, role). Raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    when either header is missing/empty or the role is not one of the four."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise errors.missing_user_context()
    if role not in ROLES:
        raise errors.missing_user_context("X-User-Role must be one of the four declared roles")
    return user_id, role


def require_roles(*allowed):
    """Priority 1 (auth context) then priority 3 (role authorization).

    Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.unauthorized_role()
    return user_id, role
