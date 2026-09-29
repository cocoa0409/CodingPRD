"""Header authentication (priority 1), endpoint authorisation (priority 2) and
domain entitlement (priority 6) per PRD 2.1 / 2.9."""

import functools

from flask import g, request

import db
from errors import fail

ROLES = ("GovernanceAdmin", "DataOwner", "DataSteward", "ConsumerRep", "Auditor")
ENTITY_BACKED = ("DataOwner", "DataSteward", "ConsumerRep")

OWNER_ROLES = ("DATA_OWNER",)
STEWARD_ROLES = ("DATA_STEWARD", "CUSTODIAN")


def endpoint(*roles):
    """Decorator running priority-1 authentication then priority-2 authorisation."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if role is None or role not in ROLES:
                fail("ERR_UNAUTHENTICATED",
                     "X-User-Role is missing or not a recognised role.")
            user_id = request.headers.get("X-User-ID")
            if user_id is not None and user_id.strip() == "":
                user_id = None
            if role in ENTITY_BACKED and user_id is None:
                fail("ERR_UNAUTHENTICATED",
                     "X-User-ID is required for the acting role.")
            if role not in roles:
                fail("ERR_UNAUTHORIZED", "The acting role may not call this endpoint.")
            g.role = role
            g.user_id = user_id
            return view(*args, **kwargs)

        return wrapper

    return decorator


def entitle(domain):
    """Priority 6 - the acting identity is entitled on the target domain."""
    role = g.role
    if role == "DataOwner":
        if not db.has_active_assignment(domain["id"], g.user_id, OWNER_ROLES):
            fail("ERR_NOT_DOMAIN_OWNER",
                 "The acting steward holds no ACTIVE DATA_OWNER assignment on this domain.")
    elif role == "DataSteward":
        if not db.has_active_assignment(domain["id"], g.user_id, STEWARD_ROLES):
            fail("ERR_NOT_DOMAIN_STEWARD",
                 "The acting steward holds no ACTIVE stewardship assignment on this domain.")


def identity_mismatch(message):
    """The acting X-User-ID does not match the steward identifier the operation
    demands.  No dedicated error id is declared, so the entitlement error of the
    acting role is used (PRD 2.1)."""
    if g.role == "DataOwner":
        fail("ERR_NOT_DOMAIN_OWNER", message)
    fail("ERR_NOT_DOMAIN_STEWARD", message)


def is_owner_of(domain):
    return db.has_active_assignment(domain["id"], g.user_id, OWNER_ROLES)
