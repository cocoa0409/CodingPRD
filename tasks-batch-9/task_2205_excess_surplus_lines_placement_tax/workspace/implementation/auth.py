"""Ladder rungs 1-3, 4-5 resolution helpers, rung 7 ownership, rung 8 OCC."""

from flask import g, request

import store
from errors import ApiError, NOT_FOUND_ERROR

ROLES = (
    "PlacementBroker",
    "ComplianceOfficer",
    "TaxFiler",
    "StateRegulator",
    "PlatformAdmin",
)

ANY = "Any"

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    """Rungs 1 and 2 — run before anything else, including path inspection."""
    user_id = request.headers.get(USER_ID_HEADER, None)
    role = request.headers.get(USER_ROLE_HEADER, None)
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not isinstance(role, str) or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    g.user_id = user_id
    g.role = role


def user_id():
    return getattr(g, "user_id", None)


def role():
    return getattr(g, "role", None)


def require(*allowed):
    """Rung 3 — the endpoint's authorised-role list."""
    if ANY in allowed:
        return
    if role() not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not perform this operation." % role())


def is_broker():
    return role() == "PlacementBroker"


# --- rung 4: path existence, left to right -------------------------------

def path_entity(collection, entity_key, rec_id):
    rec = store.db.get(collection, rec_id)
    if rec is None:
        raise ApiError(NOT_FOUND_ERROR[entity_key])
    return rec


# --- rung 5: body foreign keys, in declared field order ------------------

def body_fk(data, name, collection, entity_key, required=True):
    """Resolve a body FK. Only well-formed non-empty strings are resolved;
    a missing or non-string value falls through to rung 6."""
    value = data.get(name, None)
    if value is None or not isinstance(value, str) or value == "":
        return None
    rec = store.db.get(collection, value)
    if rec is None:
        raise ApiError(NOT_FOUND_ERROR[entity_key])
    return rec


# --- rung 7: resource ownership ------------------------------------------

def check_owner(broker_id):
    """When the acting role is PlacementBroker the resource must be its own."""
    if is_broker() and broker_id != user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The resource belongs to another brokerage.")


# --- rung 8: stale parent version ----------------------------------------

def check_version(expected, parent, error_id):
    if expected != int(parent.get("version", 0)):
        raise ApiError(error_id, "The parent record has advanced; refresh and retry.")
