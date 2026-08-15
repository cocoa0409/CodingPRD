"""Auth header extraction and role checking, per PRD section 2.1."""

from flask import request

from errors import err_unauthenticated, err_unauthorized

ROLES = {"Nurse", "ProgramAdmin", "PayrollOfficer", "RetentionAnalyst"}


def get_auth():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED on missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Validates auth then role authorization. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role
