"""Authentication, RBAC and pagination-parameter extraction (PRD 2.1 / 2.3)."""
from flask import request

from errors import ApiError
from response import PAGINATION_DEFAULTS

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_ACTIVITY_DIRECTOR = "ActivityDirector"
ROLE_RECREATION_THERAPIST = "RecreationTherapist"
ROLE_ACTIVITY_AIDE = "ActivityAide"
ROLE_VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_VOLUNTEER = "Volunteer"
ROLE_COUNCIL_REPRESENTATIVE = "CouncilRepresentative"

ALL_ROLES = (
    ROLE_ACTIVITY_DIRECTOR,
    ROLE_RECREATION_THERAPIST,
    ROLE_ACTIVITY_AIDE,
    ROLE_VOLUNTEER_COORDINATOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_VOLUNTEER,
    ROLE_COUNCIL_REPRESENTATIVE,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Rank 1: both headers present, non-empty, role recognised."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


def authorize(*allowed_roles):
    """Rank 1 then rank 2. Authorization outranks every existence check."""
    actor = authenticate()
    if actor.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return actor


def deny():
    raise ApiError("ERR_UNAUTHORIZED")


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not (text.lstrip("+-").isdigit() and text.lstrip("+-") != ""):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is below the minimum." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s is above the maximum." % name)
    return value


def pagination():
    limit = _int_param(
        "limit",
        PAGINATION_DEFAULTS["limit"],
        PAGINATION_DEFAULTS["limit_min"],
        PAGINATION_DEFAULTS["limit_max"],
    )
    offset = _int_param("offset", PAGINATION_DEFAULTS["offset"], 0, None)
    return limit, offset


def filter_arg(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None
