"""Authentication, role recognition and role permission -- PRD 2.1 and 2.10.

Rung 1: both X-User-ID and X-User-Role present and non-empty, else ERR_UNAUTHENTICATED.
Rung 2: X-User-Role names one of the six declared roles, else ERR_UNAUTHENTICATED
        (an unrecognised role is an authentication failure, never a permission one).
Rung 3: the recognised role appears in the target operation's authorised list,
        else ERR_ROLE_NOT_PERMITTED.
"""

from flask import request

from errors import ApiError


HOUSEKEEPING_DIRECTOR = "HousekeepingDirector"
SUPERVISOR = "Supervisor"
ROOM_ATTENDANT = "RoomAttendant"
LAUNDRY_LEAD = "LaundryLead"
FRONT_DESK_AGENT = "FrontDeskAgent"
COMPLIANCE_OFFICER = "ComplianceOfficer"

ALL_ROLES = (
    HOUSEKEEPING_DIRECTOR,
    SUPERVISOR,
    ROOM_ATTENDANT,
    LAUNDRY_LEAD,
    FRONT_DESK_AGENT,
    COMPLIANCE_OFFICER,
)

# The two entity-backed roles: X-User-ID is the id of the acting Attendant.
ENTITY_BACKED_ROLES = (SUPERVISOR, ROOM_ATTENDANT)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role %r is not a recognised role." % role)
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s is not permitted on this operation." % role,
        )
    return Actor(user_id, role)


def resolve_acting_attendant(store, actor):
    """PRD 2.1/2.5: for Supervisor and RoomAttendant, X-User-ID must resolve to an
    Attendant row on the operations where the identity must be resolved; a failure
    is ERR_ATTENDANT_NOT_FOUND."""
    att = store.attendants.get(actor.user_id)
    if att is None:
        raise ApiError("ERR_ATTENDANT_NOT_FOUND", "Acting attendant %s not found." % actor.user_id)
    return att
