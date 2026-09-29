"""Authentication headers, the seven roles, and ownership scoping."""
from flask import request

from errors import fail
from store import db

ALL_ROLES = (
    "ProgramAdmin",
    "FamilyServicesCoordinator",
    "SelectionCommitteeMember",
    "MortgageOfficer",
    "ConstructionManager",
    "Applicant",
    "Volunteer",
)

# Entity-backed roles resolve X-User-ID against a stored row.
ENTITY_BACKED = {
    "Applicant": "households",
    "Volunteer": "volunteers",
}

STAFF_ROLES = (
    "ProgramAdmin",
    "FamilyServicesCoordinator",
    "SelectionCommitteeMember",
    "MortgageOfficer",
    "ConstructionManager",
)


class Actor(object):
    def __init__(self, user_id, role, identity):
        self.user_id = user_id
        self.role = role
        self.identity = identity

    @property
    def is_applicant(self):
        return self.role == "Applicant"

    @property
    def is_volunteer(self):
        return self.role == "Volunteer"

    @property
    def entity_id(self):
        return self.identity["id"] if self.identity else None

    @property
    def household_id(self):
        return self.identity["id"] if self.is_applicant and self.identity else None

    @property
    def volunteer_id(self):
        return self.identity["id"] if self.is_volunteer and self.identity else None


def auth(*allowed):
    """Rejection positions 1-4: headers, unknown role, permission, identity."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        fail("ERR_MISSING_AUTH_HEADERS")
    if role not in ALL_ROLES:
        fail("ERR_UNKNOWN_ROLE")
    if allowed and role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED")
    identity = None
    if role in ENTITY_BACKED:
        identity = getattr(db, ENTITY_BACKED[role]).get(user_id)
        if identity is None:
            fail("ERR_IDENTITY_NOT_FOUND")
    return Actor(user_id, role, identity)


def own_household(actor, household):
    """Rejection position 7 for household-scoped single-row reads."""
    if actor.is_applicant and household is not None:
        if actor.household_id != household["id"]:
            fail("ERR_NOT_RESOURCE_OWNER")
    return household


def own_volunteer(actor, volunteer):
    if actor.is_volunteer and volunteer is not None:
        if actor.volunteer_id != volunteer["id"]:
            fail("ERR_NOT_RESOURCE_OWNER")
    return volunteer


def scope_households(actor, rows):
    if actor.is_applicant:
        return [r for r in rows if r["id"] == actor.household_id]
    return rows


def scope_by_household(actor, rows, key="household_id"):
    if actor.is_applicant:
        return [r for r in rows if r.get(key) == actor.household_id]
    return rows


def scope_volunteers(actor, rows):
    if actor.is_volunteer:
        return [r for r in rows if r["id"] == actor.volunteer_id]
    return rows


def scope_by_volunteer(actor, rows, key="volunteer_id"):
    if actor.is_volunteer:
        return [r for r in rows if r.get(key) == actor.volunteer_id]
    return rows
