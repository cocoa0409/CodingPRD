"""Auth header extraction and role checking (PRD §2.1, validations priority 1-2)."""

from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = ("SchedulerAdmin", "TerminalAgent", "Customer", "CrewPlanner")


def get_auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "Missing or invalid X-User-Role / X-User-ID headers")
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers, then enforce endpoint role authorization."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_error(ERR_FORBIDDEN, "Role not permitted for this endpoint")
    return user_id, role
