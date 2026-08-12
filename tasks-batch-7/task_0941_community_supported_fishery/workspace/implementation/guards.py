"""Screening-ladder rungs 24 to 53 (PRD 2.5), minus the endpoint-local ones."""
from flask import g

import store
from constants import SKIP_CAP_PER_SEASON
from errors import ApiError


# --- rung 24 ---------------------------------------------------------------

def season_not_closed(season):
    """Rung 24: "The season behind the addressed resource is not CLOSED".

    The four carve-outs -- the true-up call itself, the logical-clock setter,
    every read endpoint and the member preference update -- simply never call
    this function, "so the rung cannot make its own successors unreachable".
    """
    if season is not None and season["status"] == "CLOSED":
        raise ApiError("ERR_SEASON_CLOSED")


# --- rung 25 ---------------------------------------------------------------

def season_status(season, required):
    """Rung 25: the season is in the status the operation requires."""
    if season["status"] != required:
        raise ApiError("ERR_SEASON_NOT_OPEN",
                       "This operation requires the season to be %s." % required)


# --- rung 26 ---------------------------------------------------------------

def member_not_restricted(member):
    if member["standing"] == "RESTRICTED":
        raise ApiError("ERR_MEMBER_RESTRICTED")


# --- rung 27 ---------------------------------------------------------------

def vessel_not_suspended(vessel):
    if vessel["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_VESSEL_SUSPENDED")


# --- rung 28 ---------------------------------------------------------------

def state_in(value, allowed, message=None):
    """Rung 28: the addressed resource sits in a declared from-state.

    Also carries every other precondition the state-machine table declares for
    the transition being driven, since PRD 2.5 rung 28 is the only rung that
    speaks for a transition's own preconditions.
    """
    if value not in allowed:
        raise ApiError("ERR_INVALID_STATE", message or
                       "The resource is in state %s, which this transition does not declare."
                       % value)


def state_require(condition, message=None):
    if not condition:
        raise ApiError("ERR_INVALID_STATE", message or
                       "A precondition of the requested transition does not hold.")


# --- rung 29 ---------------------------------------------------------------

def subscription_active(sub):
    if sub["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE")


# --- rung 30 ---------------------------------------------------------------

def not_past_due(sub):
    if sub["lifecycle_status"] == "PAST_DUE":
        raise ApiError("ERR_PAYMENT_REQUIRED")


def paid_in_full(sub):
    if sub["payment_basis"] == "PREPAID_FULL_SEASON" and \
            sub["paid_cents"] < sub["commitment_cents"]:
        raise ApiError("ERR_PAYMENT_REQUIRED")


# --- rung 31 ---------------------------------------------------------------

def expected_version(supplied, parent):
    """Rung 31: the supplied expected-version field equals the parent's version.

    PRD 2.7: "No other endpoint in this system takes an expected-version field,
    and no other endpoint may reject on version grounds."
    """
    if supplied != parent["version"]:
        raise ApiError("ERR_STALE_VERSION")


# --- rung 45 / 46 / 47 -----------------------------------------------------

def window_status(window, allowed):
    if window["status"] not in allowed:
        raise ApiError("ERR_WINDOW_NOT_OPEN")


def window_has_slot(window):
    if window["slots_free"] < 1:
        raise ApiError("ERR_HUB_CAPACITY_EXCEEDED")


# --- rung 49 ---------------------------------------------------------------

def skip_cap(sub):
    if sub["skip_count"] >= SKIP_CAP_PER_SEASON:
        raise ApiError("ERR_SKIP_CAP_EXCEEDED")


# --- rung 51 ---------------------------------------------------------------

def transfer_eligible(from_sub, to_sub, remaining_delivery_count):
    if to_sub["lifecycle_status"] != "WAITLISTED":
        raise ApiError("ERR_TRANSFER_NOT_ELIGIBLE")
    if from_sub["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_TRANSFER_NOT_ELIGIBLE")
    if from_sub["member_id"] == to_sub["member_id"]:
        raise ApiError("ERR_TRANSFER_NOT_ELIGIBLE")
    if remaining_delivery_count <= 0:
        raise ApiError("ERR_TRANSFER_NOT_ELIGIBLE")


# --- rung 53 ---------------------------------------------------------------

def unique(kind, predicate):
    for rec in store.all_of(kind):
        if predicate(rec):
            raise ApiError("ERR_DUPLICATE_RESOURCE")


# --- rung 23 ---------------------------------------------------------------

def reference(condition, message=None):
    if not condition:
        raise ApiError("ERR_REFERENCE_MISMATCH", message or
                       "Two references that must agree do not.")


# --- helpers ---------------------------------------------------------------

def season_of(record):
    """The season behind an arbitrary record, for rung 24."""
    if record is None:
        return None
    kind = record["_kind"]
    if kind == "Season":
        return record
    if "season_id" in record and record.get("season_id"):
        return store.get("Season", record["season_id"])
    if kind == "SharePlan":
        return store.get("Season", record["season_id"])
    if kind == "LandingLot":
        trip = store.get("Trip", record["trip_id"])
        return store.get("Season", trip["season_id"]) if trip else None
    if kind == "SubLot":
        lot = store.get("LandingLot", record["landing_lot_id"])
        return season_of(lot)
    if kind == "ColdChainEvent":
        return season_of(store.get("LandingLot", record["landing_lot_id"]))
    if kind == "SubstitutionEvent":
        return season_of(store.get("ShareDelivery", record["share_delivery_id"]))
    if kind == "SkipRequest":
        return season_of(store.get("Subscription", record["subscription_id"]))
    if kind == "SettlementStatement":
        return season_of(store.get("Trip", record["trip_id"]))
    if kind == "Trip":
        return store.get("Season", record["season_id"])
    return None
