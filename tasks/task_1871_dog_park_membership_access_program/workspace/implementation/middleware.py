"""Auth pipeline stages 1-3 (PRD §2.7): headers, role listing, steward gate."""
from flask import request

from db import store
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_NOT_A_STEWARD,
)

DECLARED_ROLES = ("Anonymous", "Member", "Steward", "ParkAdmin")


def require_auth(allowed_roles):
    """Validate X-User-ID / X-User-Role and endpoint role listing.

    Returns (user_id, role). Raises ApiError on failure.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    # Stage 1: both headers present, role declared.
    if not uid or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
            "X-User-ID and X-User-Role headers are required and the role "
            "must be one of {}".format(sorted(DECLARED_ROLES)),
        )
    # Stage 2: caller role must be listed for the endpoint.
    if role not in allowed_roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS, 403,
            "Role {} is not authorized for this endpoint".format(role),
        )
    # Stage 3: Steward role requires the member's is_steward flag.
    if role == "Steward" and "Steward" in allowed_roles:
        member = store.members.get(uid)
        if member is None or not member["is_steward"]:
            raise ApiError(
                ERR_NOT_A_STEWARD, 403,
                "X-User-Role Steward requires a member with is_steward true",
            )
    return uid, role
