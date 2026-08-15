"""Auth header extraction and role authorization per PRD section 2.1."""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT,
)

ROLES = {"ClubAdmin", "Member", "DutyOfficer", "Instructor", "TowPilot"}


def auth():
    """Validate X-User-ID / X-User-Role presence and role recognition."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT,
            400,
            "X-User-ID and X-User-Role headers are required and the role "
            "must be one of ClubAdmin, Member, DutyOfficer, Instructor, TowPilot",
        )
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            "Role '%s' is not permitted for this endpoint" % role,
        )


def forbid(message):
    raise ApiError(ERR_FORBIDDEN_ROLE, 403, message)
