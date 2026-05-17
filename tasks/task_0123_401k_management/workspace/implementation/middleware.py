"""Auth, RBAC and segregation-of-duties middleware per PRD §2.1."""

from flask import request, g

from config import VALID_ROLES, ROLE_PARTICIPANT
from errors import (
    AppError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)


def require_auth():
    """Extract & validate X-User-ID and X-User-Role headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise AppError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or malformed X-User-ID header.",
            400,
        )
    if not role or role not in VALID_ROLES:
        raise AppError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or malformed X-User-Role header.",
            400,
        )
    g.user_id = user_id.strip()
    g.role = role


def require_role(*allowed_roles):
    """Reject the request unless the caller's role is in the allowed set."""
    if g.role not in allowed_roles:
        raise AppError(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"Role {g.role} is not authorized for this operation.",
            403,
        )


def require_self_participant(participant_id: str):
    """For Participant-role requests, X-User-ID must equal the URL participantId."""
    if g.role == ROLE_PARTICIPANT and g.user_id != participant_id:
        raise AppError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Participants may only act on themselves.",
            403,
        )
