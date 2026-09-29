"""Liquidity events, stockholder ballots and the logical clock — PRD §3.9, §2.6."""

from flask import Blueprint

import calc
import domain
import validate as V
from auth import require_roles, require_transition_role, user_id
from errors import fail
from response import object_response
from routes.helpers import listing, new, resolve, single
from store import CLOCK, DB, all_rows, fmt_instant, logical_date, new_row, touch

bp = Blueprint("liquidity", __name__)

EVENT_TYPES = ("LISTING", "MERGER", "ASSET_SALE")
EVENT_STATES = ("PROPOSED", "BOARD_APPROVED", "VOTE_OPEN", "APPROVED",
                "REJECTED", "EXECUTED", "ABANDONED")
ACTIONS = ("BOARD_APPROVE", "OPEN_VOTE", "CLOSE_VOTE", "EXECUTE", "ABANDON")
CHOICES = ("FOR", "AGAINST", "ABSTAIN")

# PRD §3.9 — the board approves, executes and abandons; the sponsor solicits.
ACTION_ROLES = {
    "BOARD_APPROVE": ("BoardCommittee",),
    "EXECUTE": ("BoardCommittee",),
    "ABANDON": ("BoardCommittee",),
    "OPEN_VOTE": ("SponsorOperator",),
    "CLOSE_VOTE": ("SponsorOperator",),
}

READ_ROLES = ("SponsorOperator", "BoardCommittee", "ComplianceOfficer",
              "TransferAgent", "InvestorUser")
CLOCK_ROLES = ("SponsorOperator", "ComplianceOfficer", "TransferAgent",
               "BoardCommittee", "IndependentValuationAdvisor",
               "BrokerDealerRep", "InvestorUser")


# --------------------------------------------------------------------------
# LiquidityEvent
# --------------------------------------------------------------------------

@bp.post("/liquidity-events")
def create_event():
    require_roles("SponsorOperator")
    body = V.json_body()
    offering_id = V.fk(body, "offering_id")
    event_type = V.enum(body, "event_type", EVENT_TYPES)
    effective_literal, effective_date = V.date_field(body, "proposed_effective_date")

    offering = resolve("offerings", offering_id)

    row = new_row("liquidity_events", {
        "offering_id": offering["id"],
        "event_type": event_type,
        "proposed_effective_date": effective_literal,
        "_effective_date": effective_date,
        "record_date_shares_e4": 0,
        "votes_for_e4": 0,
        "votes_against_e4": 0,
        "votes_abstain_e4": 0,
        "quorum_met": False,
        "status": "PROPOSED",
    })
    return new(row)


@bp.get("/liquidity-events")
def list_events():
    require_roles(*READ_ROLES)
    limit, offset = V.pagination()
    offering_id = V.query_string("offering_id")
    status = V.query_enum("status", EVENT_STATES)
    event_type = V.query_enum("event_type", EVENT_TYPES)
    rows = [e for e in all_rows("liquidity_events")
            if (offering_id is None or e["offering_id"] == offering_id)
            and (status is None or e["status"] == status)
            and (event_type is None or e["event_type"] == event_type)]
    return listing(rows, limit, offset)


@bp.get("/liquidity-events/<liquidity_event_id>")
def get_event(liquidity_event_id):
    require_roles(*READ_ROLES)
    return single(resolve("liquidity_events", liquidity_event_id))


@bp.post("/liquidity-events/<liquidity_event_id>/status")
def drive_event(liquidity_event_id):
    require_roles("SponsorOperator", "BoardCommittee")
    peek = V.json_body(silent=True)
    require_transition_role(ACTION_ROLES, peek.get("action"))
    body = V.json_body()
    action = V.enum(body, "action", ACTIONS)
    V.string(body, "reason", required=False, default=None, min_len=0)

    event = resolve("liquidity_events", liquidity_event_id)
    offering = DB["offerings"].get(event["offering_id"])
    current = event["status"]

    if action == "BOARD_APPROVE":
        if current != "PROPOSED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if offering is None or offering["escrow_status"] != "BROKEN":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "An offering that never funded has nothing to liquidate.")
        event["status"] = "BOARD_APPROVED"
        touch(event)

    elif action == "OPEN_VOTE":
        if current != "BOARD_APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if offering is None or offering["registration_status"] == "DRAFT":
            fail("ERR_INVALID_STATE_TRANSITION",
                 "The offering's registration has never been declared effective.")
        event["record_date_shares_e4"] = sum(
            c["shares_outstanding_e4"] for c in domain.classes_of(offering["id"]))
        event["status"] = "VOTE_OPEN"
        touch(event)

    elif action == "CLOSE_VOTE":
        if current != "VOTE_OPEN":
            fail("ERR_INVALID_STATE_TRANSITION")
        tallies = {"FOR": 0, "AGAINST": 0, "ABSTAIN": 0}
        for ballot in domain.votes_of_event(event["id"]):
            tallies[ballot["choice"]] += ballot["voting_shares_e4"]
        quorum_met, approved = calc.vote_outcome(
            tallies["FOR"], tallies["AGAINST"], tallies["ABSTAIN"],
            event["record_date_shares_e4"])
        event["votes_for_e4"] = tallies["FOR"]
        event["votes_against_e4"] = tallies["AGAINST"]
        event["votes_abstain_e4"] = tallies["ABSTAIN"]
        event["quorum_met"] = quorum_met
        event["status"] = "APPROVED" if approved else "REJECTED"
        touch(event)
        if approved and offering is not None and \
                offering["repurchase_plan_status"] == "ACTIVE":
            domain.suspend_plan(offering, "LIQUIDITY_EVENT_APPROVED")

    elif action == "EXECUTE":
        if current != "APPROVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        if logical_date() < event["_effective_date"]:
            fail("ERR_EFFECTIVE_DATE_NOT_REACHED")
        event["status"] = "EXECUTED"
        touch(event)
        if offering is not None:
            domain.set_field(offering, "registration_status", "CLOSED")
            domain.set_field(offering, "repurchase_plan_status", "TERMINATED")
            domain.close_active_classes(offering)

    else:  # ABANDON
        if current not in ("PROPOSED", "BOARD_APPROVED", "VOTE_OPEN", "REJECTED"):
            fail("ERR_INVALID_STATE_TRANSITION")
        event["status"] = "ABANDONED"
        touch(event)

    domain.sync_derived()
    return single(event)


# --------------------------------------------------------------------------
# StockholderVote
# --------------------------------------------------------------------------

@bp.post("/stockholder-votes")
def cast_ballot():
    require_roles("InvestorUser")
    body = V.json_body()
    event_id = V.fk(body, "liquidity_event_id")
    choice = V.enum(body, "choice", CHOICES)

    event = resolve("liquidity_events", event_id)

    # Level 5 — the ballot belongs to the acting stockholder.
    investor = DB["investors"].get(user_id())
    if investor is None:
        fail("ERR_NOT_RESOURCE_OWNER")

    # Level 8 — the solicitation must be open.
    if event["status"] != "VOTE_OPEN":
        fail("ERR_VOTE_NOT_OPEN")

    # Level 11 — one ballot per stockholder per event.
    for ballot in domain.votes_of_event(event["id"]):
        if ballot["investor_id"] == investor["id"]:
            fail("ERR_DUPLICATE_STOCKHOLDER_VOTE")

    row = new_row("stockholder_votes", {
        "liquidity_event_id": event["id"],
        "investor_id": investor["id"],
        "choice": choice,
        "voting_shares_e4": investor["total_shares_e4"],
    }, common=False)
    return new(row)


@bp.get("/stockholder-votes")
def list_ballots():
    require_roles(*READ_ROLES)
    limit, offset = V.pagination()
    event_id = V.query_string("liquidity_event_id")
    investor_id = V.query_string("investor_id")
    choice = V.query_enum("choice", CHOICES)
    rows = [v for v in all_rows("stockholder_votes")
            if (event_id is None or v["liquidity_event_id"] == event_id)
            and (investor_id is None or v["investor_id"] == investor_id)
            and (choice is None or v["choice"] == choice)]
    return listing(rows, limit, offset)


@bp.get("/stockholder-votes/<stockholder_vote_id>")
def get_ballot(stockholder_vote_id):
    require_roles(*READ_ROLES)
    return single(resolve("stockholder_votes", stockholder_vote_id))


# --------------------------------------------------------------------------
# Logical clock — PRD §2.6
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(*CLOCK_ROLES)
    body = V.json_body()
    literal, instant = V.instant_field(body, "current_utc")
    previous = CLOCK.get("literal") or fmt_instant(CLOCK["now"])
    CLOCK["now"] = instant
    CLOCK["literal"] = literal
    return object_response({"current_utc": literal, "previous_utc": previous})
