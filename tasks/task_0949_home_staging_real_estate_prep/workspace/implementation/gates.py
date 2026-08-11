"""The ten write gates / seventy-three rung ladder (PRD section 2.7).

Every helper here is named for the rung it implements so the evaluation order
in each handler can be read straight off the ladder.
"""
import functools

from flask import g, request

import store
from consts import ENTITY_BACKED_ROLES, ROLES
from errors import NOT_FOUND, ApiError

# ==========================================================================
# G1 / G2
# ==========================================================================


def endpoint(*roles):
    """Rungs 1-4: authentication then authorization."""
    allowed = set(roles)

    def wrapper(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            if role is None or role == "":
                raise ApiError("ERR_UNAUTHENTICATED")                 # rung 1
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")                 # rung 2
            user_id = request.headers.get("X-User-ID")
            if role in ENTITY_BACKED_ROLES and (user_id is None or user_id == ""):
                raise ApiError("ERR_IDENTITY_REQUIRED")               # rung 3
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")                    # rung 4
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)
        return inner
    return wrapper


def role():
    return getattr(g, "role", None)


def actor():
    return getattr(g, "user_id", None)


# ==========================================================================
# G3 - rung 5: path resolution, strictly left to right
# ==========================================================================


def path_row(collection, row_id):
    row = store.get(collection, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[collection])
    return row


# ==========================================================================
# G3 - rungs 6..9: body shape
# ==========================================================================


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        parsed = None
    if parsed is None:
        return None
    return parsed


def require(payload, fields):
    """Rung 6."""
    if not isinstance(payload, dict):
        raise ApiError("ERR_MISSING_FIELD", "The request body must be a JSON object.")
    for name in fields:
        if name not in payload or payload[name] is None:
            raise ApiError("ERR_MISSING_FIELD", "Required field '%s' is missing." % name)


def enums(payload, spec):
    """Rung 7 - the closed list of enum-typed body fields."""
    for name, members in spec.items():
        if name in payload and payload[name] is not None:
            if payload[name] not in members:
                raise ApiError("ERR_INVALID_ENUM",
                               "Field '%s' is not a member of its declared set." % name)


def _bad(name):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is of the wrong type or out of range." % name)


def types(payload, spec):
    """Rung 8 - declared type and numeric range."""
    for name, rule in spec.items():
        if name not in payload or payload[name] is None:
            continue
        value = payload[name]
        kind = rule[0]
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                _bad(name)
            lo, hi = rule[1], rule[2]
            if lo is not None and value < lo:
                _bad(name)
            if hi is not None and value > hi:
                _bad(name)
        elif kind == "num":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _bad(name)
            lo, hi = rule[1], rule[2]
            if lo is not None and float(value) < float(lo):
                _bad(name)
            if hi is not None and float(value) > float(hi):
                _bad(name)
        elif kind == "num_ex":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _bad(name)
            lo, hi = rule[1], rule[2]
            if lo is not None and float(value) <= float(lo):
                _bad(name)
            if hi is not None and float(value) >= float(hi):
                _bad(name)
        elif kind == "str":
            if not isinstance(value, str):
                _bad(name)
        elif kind == "bool":
            if not isinstance(value, bool):
                _bad(name)
        elif kind == "dt":
            if not isinstance(value, str) or store.parse_dt(value) is None:
                _bad(name)
    return payload


def fks(payload, spec):
    """Rung 9 - body foreign keys resolve to a stored row of the declared type."""
    for name, collection in spec.items():
        if name not in payload or payload[name] is None:
            continue
        if not isinstance(payload[name], str) or store.get(collection, payload[name]) is None:
            raise ApiError(NOT_FOUND[collection])


# ==========================================================================
# G4 - party scope, rungs 10..13
# ==========================================================================


def rung10_listing_agent(listing):
    if role() == "ListingAgent":
        if listing is None or actor() != listing.get("listing_agent_client_id"):
            raise ApiError("ERR_NOT_LISTING_AGENT")


def rung11_property_owner(prop):
    if role() == "Seller":
        if prop is None or actor() != prop.get("owner_client_id"):
            raise ApiError("ERR_NOT_PROPERTY_OWNER")


def rung12_project_party(project):
    if role() == "BrokerageAdmin":
        if project is None or actor() != project.get("brokerage_id"):
            raise ApiError("ERR_NOT_PROJECT_PARTY")


def rung13_order_vendor(order):
    if role() == "VendorRep":
        if order is None or actor() != order.get("vendor_id"):
            raise ApiError("ERR_NOT_ORDER_VENDOR")


# ==========================================================================
# G5 - global freeze, rungs 14..17
# ==========================================================================


def rung14_project_closed(project):
    if project is not None and project.get("workflow_state") == "CLOSED":
        raise ApiError("ERR_PROJECT_CLOSED")


def rung15_listing_terminated(listing):
    if listing is not None and listing.get("listing_state") == "TERMINATED":
        raise ApiError("ERR_LISTING_TERMINATED")


def rung16_listing_closed(listing):
    if listing is not None and listing.get("listing_state") == "CLOSED_SOLD":
        raise ApiError("ERR_LISTING_CLOSED")


def rung17_consultation_cancelled(consultation):
    if consultation is not None and consultation.get("state") == "CANCELLED":
        raise ApiError("ERR_CONSULTATION_INVALID_STATE")


def freeze_project(project, listing=None, execution=False):
    """The standard freeze bundle for an endpoint that hangs off a project."""
    rung14_project_closed(project)
    rung15_listing_terminated(listing)
    if execution:
        rung16_listing_closed(listing)


# ==========================================================================
# G6 - rung 34
# ==========================================================================


def rung34_not_too_early(scheduled_at):
    if scheduled_at is not None and store.now() < scheduled_at:
        raise ApiError("ERR_EVENT_TOO_EARLY")


# ==========================================================================
# G7 - rungs 35..37
# ==========================================================================


def occ(payload, field, parent, error_id):
    supplied = payload.get(field)
    if supplied != parent.get("version"):
        raise ApiError(error_id)


# ==========================================================================
# G10 - rung 71
# ==========================================================================


def rung71_fiscal_hold(project):
    if project.get("fiscal_hold"):
        raise ApiError("ERR_FISCAL_HOLD")
