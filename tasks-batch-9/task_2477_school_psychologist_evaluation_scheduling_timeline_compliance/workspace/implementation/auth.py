"""Authentication and RBAC (PRD §2.1, validation ladder positions 1 and 2)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "IntakeCoordinator",
    "SchoolPsychologist",
    "PsychServicesSupervisor",
    "ComplianceOfficer",
    "DistrictAdmin",
)

ALL_ROLES = ROLES


def authorize(*allowed_roles):
    """Ladder 1: X-User-ID and X-User-Role present, role recognized -> 401.
    Ladder 2: role listed for this endpoint -> 403.
    """
    allowed = tuple(allowed_roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if user_id is None or user_role is None or user_id.strip() == "" or user_role.strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
            if user_role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognized role.")
            if user_role not in allowed:
                raise ApiError("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % user_role)
            g.user_id = user_id
            g.user_role = user_role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)
