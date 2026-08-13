"""Auth header extraction and role checking (PRD §2.1, validation priorities 1-3)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

ROLES = ["LPAnalyst", "LPManager", "HRPartner", "LPAdmin", "Auditor", "PosFeed"]

ALL_ROLES = set(ROLES)


def get_auth():
    """Priority 1: header presence/validity. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID header missing or malformed",
            400,
        )
    if not role or role not in ALL_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role header missing or not one of the six declared roles",
            400,
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role permission for the endpoint."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Role %s is not permitted for this endpoint" % role,
            403,
        )
