"""Auth header extraction and role gate (PRD 2.1, 2.11 rungs 1-3)."""

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

ROLES = (
    "ProgramAdmin",
    "Landowner",
    "AcquisitionOfficer",
    "AppraisalReviewer",
    "Appraiser",
    "StewardshipMonitor",
)


def authenticate(allowed_roles):
    """Rung 1: X-User-ID present. Rung 2: X-User-Role is a known role.
    Rung 3: the role is permitted for this endpoint."""
    user_id = request.headers.get(USER_ID_HEADER)
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    user_id = str(user_id).strip()

    role = request.headers.get(ROLE_HEADER)
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role")

    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation" % role
        )

    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_owner(expected_user_id):
    """Rung 7: ownership. Landowner identity header must equal the owning id."""
    if g.get("user_id") != expected_user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "Caller does not own the targeted resource"
        )
