"""Auth header extraction and role checking (PRD §2.1, scaffold §1.4 priorities 1-2)."""
from flask import request

from errors import ApiError

ROLE_ADMIN = "ProgramAdmin"
ROLE_COACH = "Coach"
ROLE_PARTICIPANT = "Participant"
VALID_ROLES = {ROLE_ADMIN, ROLE_COACH, ROLE_PARTICIPANT}


def actor():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED (401) when the
    X-User-ID / X-User-Role headers are missing or the role is undeclared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Missing or invalid X-User-ID / X-User-Role headers.",
            401,
        )
    return uid, role


def require_roles(*roles):
    """Authentication (401) plus endpoint-level role permission (403)."""
    uid, role = actor()
    if role not in roles:
        raise ApiError(
            "ERR_FORBIDDEN", "Role %s is not permitted for this endpoint." % role, 403
        )
    return uid, role


def forbidden(message="Entity-backed ownership check failed."):
    raise ApiError("ERR_FORBIDDEN", message, 403)
