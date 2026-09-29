"""Shared lookups, query filtering and the carrier-fitness gate of PRD §2.10."""
from flask import request

import store
from errors import ApiError

# Standing eligible to be bound to new commercial obligations (PRD §2.10).
STANDING_ELIGIBLE = ("QUALIFIED", "CONDITIONALLY_QUALIFIED", "WATCHLIST")
# The award-approval gate is narrower (PRD §3.7).
STANDING_APPROVAL = ("QUALIFIED", "CONDITIONALLY_QUALIFIED")


def get_carrier(row_id):
    return store.require(store.carriers, row_id, "ERR_CARRIER_NOT_FOUND")


def get_review(row_id):
    return store.require(store.reviews, row_id, "ERR_QUALIFICATION_REVIEW_NOT_FOUND")


def get_event(row_id):
    return store.require(store.events, row_id, "ERR_BID_EVENT_NOT_FOUND")


def get_lane(row_id):
    return store.require(store.lanes, row_id, "ERR_LANE_NOT_FOUND")


def get_round(row_id):
    return store.require(store.rounds, row_id, "ERR_BID_ROUND_NOT_FOUND")


def get_invitation(row_id):
    return store.require(store.invitations, row_id, "ERR_INVITATION_NOT_FOUND")


def get_bid(row_id):
    return store.require(store.lane_bids, row_id, "ERR_LANE_BID_NOT_FOUND")


def get_run(row_id):
    return store.require(store.runs, row_id, "ERR_OPTIMIZATION_RUN_NOT_FOUND")


def get_allocation(row_id):
    return store.require(store.allocations, row_id, "ERR_AWARD_ALLOCATION_NOT_FOUND")


def get_contract(row_id):
    return store.require(store.contracts, row_id, "ERR_CONTRACT_NOT_FOUND")


def get_rate_record(row_id):
    return store.require(store.rate_records, row_id, "ERR_RATE_RECORD_NOT_FOUND")


def get_mini_bid(row_id):
    return store.require(store.mini_bids, row_id, "ERR_MINI_BID_NOT_FOUND")


def get_scorecard(row_id):
    return store.require(store.scorecards, row_id, "ERR_SCORECARD_NOT_FOUND")


def event_of(row):
    """The bid event governing a row that carries bid_event_id."""
    return store.events.get(row.get("bid_event_id"))


def check_fitness(carrier, standing=STANDING_ELIGIBLE, require_standing=True):
    """The three fitness checks, distinguishable by their error identifiers and taken in
    a fixed order.  The certificate must expire strictly after the current instant, so a
    certificate expiring exactly now is expired."""
    if carrier["status"] in ("SUSPENDED", "DISQUALIFIED"):
        raise ApiError("ERR_CARRIER_SUSPENDED")
    expiry = store.dt_of(carrier["insurance_expiry_date"])
    if expiry is None or expiry <= store.now():
        raise ApiError("ERR_CARRIER_INSURANCE_EXPIRED")
    if require_standing and carrier["status"] not in standing:
        raise ApiError("ERR_CARRIER_NOT_QUALIFIED")


def filter_rows(rows, mapping):
    """Apply the collection's declared, always-optional query filters."""
    out = rows
    for param, field in mapping.items():
        value = request.args.get(param)
        if value is None or value == "":
            continue
        out = [r for r in out if _matches(r.get(field), value)]
    return out


def _matches(stored, wanted):
    if stored is None:
        return False
    if isinstance(stored, bool):
        return str(stored).lower() == wanted.lower()
    return str(stored) == wanted
