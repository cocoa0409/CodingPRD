"""Authentication / RBAC (PRD 2.1, validation priorities 1-3)."""

import functools

from flask import g, request

from errors import ApiError

GRID_PLANNER = "GridPlanner"
METEOROLOGY_ANALYST = "MeteorologyAnalyst"
PSPS_DUTY_OFFICER = "PSPSDutyOfficer"
COMMUNITY_LIAISON = "CommunityLiaison"
FIELD_PATROL_SUPERVISOR = "FieldPatrolSupervisor"
ASSET_INSPECTOR = "AssetInspector"
REGULATORY_REVIEWER = "RegulatoryReviewer"
TRANSMISSION_ENGINEER = "TransmissionEngineer"

ALL_ROLES = (
    GRID_PLANNER,
    METEOROLOGY_ANALYST,
    PSPS_DUTY_OFFICER,
    COMMUNITY_LIAISON,
    FIELD_PATROL_SUPERVISOR,
    ASSET_INSPECTOR,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)

    # Priority 1 - both identity headers present.
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "Both %s and %s are required." % (USER_HEADER, ROLE_HEADER))

    # Priority 2 - the role names one of the eight declared roles.
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unrecognised role '%s'." % role)

    # Priority 3 - the role is authorised for this operation.
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role '%s' may not perform this operation." % role)

    g.user_id = user_id
    g.role = role
    return user_id, role


def roles(*allowed):
    allowed_roles = tuple(allowed)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate(allowed_roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.get("user_id")
