"""Authentication, role gating and participant scoping (PRD 2.1 / 2.9)."""
from flask import request

from errors import ApiError

HIE_ADMIN = "HieAdmin"
PARTICIPANT_ADMIN = "ParticipantAdmin"
CLINICIAN = "Clinician"
PRIVACY_OFFICER = "PrivacyOfficer"
PUBLIC_HEALTH_OFFICER = "PublicHealthOfficer"

ALL_ROLES = (
    HIE_ADMIN,
    PARTICIPANT_ADMIN,
    CLINICIAN,
    PRIVACY_OFFICER,
    PUBLIC_HEALTH_OFFICER,
)

# Roles whose X-User-ID is entity-backed: it equals a Participant id (PRD 2.1).
ENTITY_BACKED_ROLES = (PARTICIPANT_ADMIN, PUBLIC_HEALTH_OFFICER)

# Purpose-of-use gating per role (PRD 2.1).
PURPOSE_BY_ROLE = {
    CLINICIAN: ("TREATMENT",),
    PARTICIPANT_ADMIN: ("PAYMENT", "OPERATIONS"),
    PUBLIC_HEALTH_OFFICER: ("PUBLIC_HEALTH", "TREATMENT"),
}

PURPOSE_DOMAIN = (
    "TREATMENT",
    "PAYMENT",
    "OPERATIONS",
    "PUBLIC_HEALTH",
    "EMERGENCY",
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def entity_backed(self):
        return self.role in ENTITY_BACKED_ROLES


def authenticate(allowed_roles):
    """Validation 1 then validation 2."""
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = role.strip()
    user_id = request.headers.get("X-User-ID") or ""
    user_id = user_id.strip()
    if role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return Actor(user_id, role)


def require_action_role(actor, action, action_roles):
    """Validation 3.  Silent when the action value is not a declared action so
    that the schema layer can report it as ERR_INVALID_REQUEST."""
    if action is None or not isinstance(action, str):
        return
    allowed = action_roles.get(action)
    if allowed is None:
        return
    if actor.role not in allowed:
        raise ApiError("ERR_ACTION_NOT_PERMITTED_FOR_ROLE")


def require_scope(actor, participant_id):
    """Validation 4.  Entity-backed roles may only act inside their own org."""
    if not actor.entity_backed:
        return
    if participant_id is None:
        return
    if actor.user_id != participant_id:
        raise ApiError("ERR_PARTICIPANT_SCOPE_VIOLATION")


def require_purpose(actor, purpose):
    """Validation 5."""
    if purpose is None or not isinstance(purpose, str):
        return
    if purpose not in PURPOSE_DOMAIN:
        return
    allowed = PURPOSE_BY_ROLE.get(actor.role)
    if allowed is None:
        return
    if purpose not in allowed:
        raise ApiError("ERR_PURPOSE_NOT_PERMITTED_FOR_ROLE")
