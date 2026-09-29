"""Authentication, role authorisation and ownership checks (PRD 2.1, ladder rungs 1-4)."""

from flask import request

from errors import fail

MEMBER = "Member"
PARK_MANAGER = "ParkManager"
CLUB_ADMIN = "ClubAdmin"
COMPLIANCE_OFFICER = "ComplianceOfficer"
TRANSIENT_GUEST = "TransientGuest"

ALL_ROLES = (MEMBER, PARK_MANAGER, CLUB_ADMIN, COMPLIANCE_OFFICER, TRANSIENT_GUEST)
VALID_ROLES = set(ALL_ROLES)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == MEMBER

    @property
    def is_park_manager(self):
        return self.role == PARK_MANAGER


def authorize(*allowed_roles):
    """Ladder rung 1 (ERR_UNAUTHENTICATED) then rung 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or invalid authentication headers")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return Actor(user_id, role)


def authorize_clock():
    """The logical-clock hook is exempt from rung 1; rung 2 still applies."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is not None and role != "" and role not in VALID_ROLES:
        fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return Actor(user_id, role)


def require_member_owner(actor, membership):
    """Ladder rung 3 — only enforced when the actor is a Member."""
    if actor.role != MEMBER or membership is None:
        return
    if membership.get("member_id") != actor.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "member does not hold this membership")


def require_park_manager(actor, park_id):
    """Ladder rung 4 — only enforced when the actor is a ParkManager."""
    if actor.role != PARK_MANAGER or park_id is None:
        return
    if park_id != actor.user_id:
        fail("ERR_NOT_PARK_MANAGER", "park manager may only act on their own park")
