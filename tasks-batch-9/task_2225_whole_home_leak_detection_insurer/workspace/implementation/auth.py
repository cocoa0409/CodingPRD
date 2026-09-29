"""Steps 1, 2, 6 and 7 of the normative admission order (PRD section 2.5)."""
from flask import request

import db
from config import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE, ROLE_HOMEOWNER
from errors import ApiError


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_homeowner(self):
        return self.role == ROLE_HOMEOWNER


def authenticate():
    """Step 1: both headers present and the role recognised."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is missing or not a recognised role.")
    return Actor(user_id, role)


def authorize(actor, *roles):
    """Step 2: the acting role must appear in the endpoint's authorised set."""
    if actor.role not in roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Role %s may not perform this operation." % actor.role
        )
    return actor


def guard(*roles):
    """Convenience: authenticate then authorise in one call."""
    actor = authenticate()
    authorize(actor, *roles)
    return actor


# ---------------------------------------------------------------- ownership
def own(actor, owner_id):
    """Step 6: a Homeowner may act only inside their own account."""
    if actor.is_homeowner and owner_id != actor.user_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "This resource belongs to a different homeowner account."
        )


def own_homeowner(actor, homeowner_row):
    own(actor, homeowner_row["id"])


def own_property(actor, row):
    own(actor, db.owner_of_property(row))


def own_device(actor, row):
    own(actor, db.owner_of_device(row))


def own_event(actor, row):
    own(actor, db.owner_of_event(row))


def own_ticket(actor, row):
    own(actor, db.owner_of_ticket(row))


def own_policy(actor, row):
    own(actor, db.owner_of_policy(row))


def own_attestation(actor, row):
    own(actor, db.owner_of_attestation(row))


def own_claim(actor, row):
    own(actor, db.owner_of_claim(row))


def own_transfer(actor, row):
    # A transfer is visible to both parties to the sale.
    if not actor.is_homeowner:
        return
    if actor.user_id in (row.get("from_homeowner_id"), row.get("to_homeowner_id")):
        return
    own(actor, db.owner_of_transfer(row))


# ---------------------------------------------------------------- liveness
def alive(homeowner_row):
    """Step 7: the resolved homeowner must still be ACTIVE."""
    if homeowner_row is None:
        return
    if homeowner_row.get("account_state") != "ACTIVE":
        raise ApiError(
            "ERR_HOMEOWNER_DEACTIVATED",
            "The homeowner account behind this request is deactivated.",
        )


def alive_id(homeowner_id):
    alive(db.homeowners.get(homeowner_id))


def alive_property(property_row):
    alive_id(property_row["homeowner_id"])


def alive_device(device_row):
    prop = db.properties.get(device_row["property_id"])
    if prop is not None:
        alive_id(prop["homeowner_id"])
