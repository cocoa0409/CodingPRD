"""Auth header extraction, role checking, and grower-ownership chains (PRD §2.1).

Every request must carry X-User-ID and X-User-Role, both present and non-empty
(ERR_UNAUTHENTICATED otherwise). The six recognized roles are
IntegratorAdmin, FieldTech, Grower, FeedMill, TransportCoordinator,
EnvironmentalManager. A caller whose role is not on an endpoint's list is
rejected with ERR_FORBIDDEN_ROLE.

When X-User-Role is Grower, X-User-ID is the id of the acting Grower entity,
and the resource's grower chain must resolve to it (ERR_NOT_RESOURCE_OWNER):
  - pig group   -> its contract's grower_id
  - maintenance ticket -> its own grower_id
  - settlement  -> its contract's grower_id
  - barn        -> the ACTIVE contract on the barn's site -> that contract's grower_id
For the other five roles X-User-ID is an opaque operator identifier.
"""

from flask import request

from db import store
from errors import (
    unauthenticated,
    forbidden_role,
    not_resource_owner,
)

ROLE_INTEGRATOR_ADMIN = "IntegratorAdmin"
ROLE_FIELD_TECH = "FieldTech"
ROLE_GROWER = "Grower"
ROLE_FEED_MILL = "FeedMill"
ROLE_TRANSPORT_COORDINATOR = "TransportCoordinator"
ROLE_ENVIRONMENTAL_MANAGER = "EnvironmentalManager"

ALL_ROLES = [
    ROLE_INTEGRATOR_ADMIN,
    ROLE_FIELD_TECH,
    ROLE_GROWER,
    ROLE_FEED_MILL,
    ROLE_TRANSPORT_COORDINATOR,
    ROLE_ENVIRONMENTAL_MANAGER,
]


def authenticate():
    """Priority 1: the two auth headers must be present and non-empty."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role.strip() == "" or user_id.strip() == "":
        raise unauthenticated()
    return role, user_id


def require_roles(allowed):
    """Priority 1 then priority 2 (endpoint role list). Returns (role, user_id)."""
    role, user_id = authenticate()
    if role not in allowed:
        raise forbidden_role()
    return role, user_id


# --- grower-chain resolution (priority 3) -----------------------------------

def group_owner_id(group):
    contract = store.contracts.get(group["contract_id"])
    return contract["grower_id"] if contract else None


def barn_owner_id(barn):
    """The ACTIVE contract on the barn's site -> its grower_id (None if none)."""
    for c in store.contracts.values():
        if c["site_id"] == barn["site_id"] and c["contract_status"] == "ACTIVE":
            return c["grower_id"]
    return None


def ticket_owner_id(ticket):
    return ticket.get("grower_id")


def settlement_owner_id(settlement):
    contract = store.contracts.get(settlement["contract_id"])
    return contract["grower_id"] if contract else None


def check_grower_ownership(role, user_id, owner_id):
    """Priority 3: on Grower-role endpoints the chain must resolve to the caller."""
    if role == ROLE_GROWER and user_id != owner_id:
        raise not_resource_owner()
