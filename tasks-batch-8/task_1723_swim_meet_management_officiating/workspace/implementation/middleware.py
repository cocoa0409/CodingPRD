"""Auth context extraction and role gating (PRD section 2.1)."""

from flask import request

from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_err,
)

ROLES = {
    "MeetDirector",
    "TeamCoach",
    "TimingOperator",
    "DeckOfficial",
    "MeetReferee",
    "RecordsOfficer",
}


def ctx():
    """Validate X-User-ID / X-User-Role; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be declared",
        )
    return user_id, role


def require_role(role, *allowed):
    if role not in allowed:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "role %s is not permitted here" % role)
