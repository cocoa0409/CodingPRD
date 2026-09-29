"""Authentication and role checks (PRD 2.1, precedence rules 1-3)."""

from flask import request

from constants import ROLES
from errors import fail


class Actor:
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Rule 1: both headers present and X-User-Role is one of the eight roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role '%s' is not a declared role." % role)
    return Actor(str(user_id).strip(), role)


def require(allowed_roles):
    """Rules 1 then 2, in that order."""
    actor = authenticate()
    if actor.role not in allowed_roles:
        fail(
            "ERR_FORBIDDEN_ROLE",
            "Role %s is not authorized for this operation." % actor.role,
        )
    return actor


def require_crew_ownership(actor, schedule):
    """Rule 3: CrewLead may only act on its own crew's schedule."""
    if actor.role == "CrewLead" and actor.user_id != schedule["installation_crew_id"]:
        fail(
            "ERR_CREW_NOT_ASSIGNED",
            "This schedule is booked to another installation crew.",
        )
