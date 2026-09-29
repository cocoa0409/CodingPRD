"""Inquiries, qualification, quotation packages and options (PRD §3.2 - §3.4)."""

from flask import Blueprint, g

import db
import errors
import validators as v
from errors import fail
from middleware import (
    get_client,
    get_inquiry,
    get_option,
    get_proposal,
    get_speaker,
    inquiry_of_proposal,
    own_inquiry,
    own_proposal,
    roles,
)
from response import ok, paged
from services import calc, lifecycle
from store import new_row, public, touch
from timeutil import fmt_iso, whole_days

bp = Blueprint("pipeline", __name__)

LIVE_PROPOSAL_STATES = ("DRAFT", "PRESENTED", "REVISION_REQUESTED")


# --- inquiries --------------------------------------------------------------

@bp.post("/inquiries")
@roles("BookingAgent", "BureauAdmin")
def create_inquiry():
    data = v.body()
    client_id = v.req_string(data, "client_id")
    required_topic = v.req_enum(data, "required_topic", v.TOPIC_CODES)
    start_raw, start_dt = v.req_dt(data, "event_start_utc")
    end_raw, end_dt = v.req_dt(data, "event_end_utc")
    audience_size = v.req_int(data, "audience_size", 1)
    budget_cents = v.req_cents(data, "budget_cents")
    objective_tags = v.req_code_list(data, "objective_tags", v.OBJECTIVE_TAGS, 1, 4)
    is_virtual = v.opt_bool(data, "is_virtual", False)

    if end_dt <= start_dt:
        fail(errors.ERR_EVENT_WINDOW_INVALID)

    client = get_client(client_id)

    inquiry = new_row({
        "client_id": client["id"],
        "owning_agent_user_id": None,
        "required_topic": required_topic,
        "event_start_utc": start_raw,
        "event_end_utc": end_raw,
        "is_virtual": is_virtual,
        "audience_size": audience_size,
        "budget_cents": budget_cents,
        "objective_tags": objective_tags,
        "status": "RECEIVED",
        "qualification_note": None,
        "_event_start_dt": start_dt,
        "_event_end_dt": end_dt,
    })
    db.inquiries[inquiry["id"]] = inquiry
    return ok(public(inquiry), 201)


@bp.get("/inquiries")
@roles("BureauAdmin", "BookingAgent", "Client")
def list_inquiries():
    client_id = v.query_string("client_id")
    agent = v.query_string("owning_agent_user_id")
    status = v.query_string("status")
    required_topic = v.query_string("required_topic")
    rows = []
    for row in db.inquiries.values():
        if client_id is not None and row["client_id"] != client_id:
            continue
        if agent is not None and row["owning_agent_user_id"] != agent:
            continue
        if status is not None and row["status"] != status:
            continue
        if required_topic is not None and row["required_topic"] != required_topic:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/inquiries/<inquiry_id>")
@roles("BureauAdmin", "BookingAgent", "Client")
def read_inquiry(inquiry_id):
    return ok(public(get_inquiry(inquiry_id)))


@bp.post("/inquiries/<inquiry_id>/qualify")
@roles("BookingAgent")
def qualify_inquiry(inquiry_id):
    inquiry = get_inquiry(inquiry_id)
    data = v.body()
    outcome = v.req_enum(data, "outcome", v.QUALIFY_OUTCOMES)
    note = v.opt_string(data, "qualification_note")

    if inquiry["status"] != "RECEIVED":
        fail(errors.ERR_INQUIRY_STATE_INVALID)

    if outcome == "QUALIFY":
        client = db.clients[inquiry["client_id"]]
        if client["credit_status"] == "HOLD":
            fail(errors.ERR_CLIENT_CREDIT_HOLD)
        lead_days = _whole_days_to_event(inquiry)
        if lead_days < calc.MIN_LEAD_DAYS:
            fail(errors.ERR_INSUFFICIENT_LEAD_TIME)
        if inquiry["budget_cents"] < calc.MIN_BUDGET_CENTS:
            fail(errors.ERR_BUDGET_BELOW_FLOOR)

    inquiry["owning_agent_user_id"] = g.user_id
    inquiry["qualification_note"] = note
    inquiry["status"] = "QUALIFIED" if outcome == "QUALIFY" else "DISQUALIFIED"
    touch(inquiry)
    return ok(public(inquiry))


def _whole_days_to_event(inquiry):
    return whole_days(inquiry["_event_start_dt"], db.now_utc())


# --- proposal rounds --------------------------------------------------------

@bp.post("/inquiries/<inquiry_id>/proposals")
@roles("BookingAgent")
def create_proposal(inquiry_id):
    inquiry = get_inquiry(inquiry_id)
    data = v.body()
    expected_version = v.req_int(data, "expected_inquiry_version")
    valid_raw, valid_dt = v.req_dt(data, "valid_until_utc")

    own_inquiry(inquiry)

    if expected_version != inquiry["version"]:
        fail(errors.ERR_STALE_INQUIRY_VERSION)

    if inquiry["status"] not in ("QUALIFIED", "PROPOSED"):
        fail(errors.ERR_INQUIRY_STATE_INVALID)

    had_presented = False
    for existing in list(db.proposals.values()):
        if existing["inquiry_id"] != inquiry["id"]:
            continue
        if existing["status"] not in LIVE_PROPOSAL_STATES:
            continue
        if existing["status"] == "PRESENTED":
            had_presented = True
        existing["status"] = "SUPERSEDED"
        for option in lifecycle.options_of(existing["id"]):
            if option["status"] == "OFFERED":
                option["status"] = "WITHDRAWN"
                touch(option)
        lifecycle.recount_options(existing)
        touch(existing)

    if had_presented and inquiry["status"] == "PROPOSED":
        inquiry["status"] = "QUALIFIED"

    proposal = new_row({
        "inquiry_id": inquiry["id"],
        "created_by_agent_user_id": g.user_id,
        "round_no": 1,
        "revision_count": 0,
        "valid_until_utc": valid_raw,
        "status": "DRAFT",
        "options_count": 0,
        "presented_at_utc": None,
        "_valid_until_dt": valid_dt,
    })
    db.proposals[proposal["id"]] = proposal
    touch(inquiry)
    return ok(public(proposal), 201)


@bp.get("/proposals")
@roles("BureauAdmin", "BookingAgent", "Client")
def list_proposals():
    inquiry_id = v.query_string("inquiry_id")
    status = v.query_string("status")
    round_no = v.query_int("round_no")
    rows = []
    for row in db.proposals.values():
        if inquiry_id is not None and row["inquiry_id"] != inquiry_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if round_no is not None and row["round_no"] != round_no:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/proposals/<proposal_id>")
@roles("BureauAdmin", "BookingAgent", "Client")
def read_proposal(proposal_id):
    return ok(public(get_proposal(proposal_id)))


# --- options ----------------------------------------------------------------

@bp.post("/proposal-options")
@roles("BookingAgent")
def create_option():
    data = v.body()
    proposal_id = v.req_string(data, "proposal_id")
    speaker_id = v.req_string(data, "speaker_id")
    quoted_fee = v.req_cents(data, "quoted_fee_cents")
    rank_no = v.req_int(data, "rank_no", 1, 4)
    travel_allowance = v.opt_cents(data, "travel_allowance_cents", 0)

    proposal = get_proposal(proposal_id)
    speaker = get_speaker(speaker_id)

    own_proposal(proposal)

    if proposal["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail(errors.ERR_PROPOSAL_STATE_INVALID)

    inquiry = inquiry_of_proposal(proposal)

    if speaker["roster_status"] != "ACTIVE":
        fail(errors.ERR_SPEAKER_NOT_ACTIVE)
    if inquiry["required_topic"] not in speaker["topics"]:
        fail(errors.ERR_TOPIC_NOT_IN_ROSTER)

    siblings = lifecycle.options_of(proposal["id"])
    if proposal["options_count"] >= calc.MAX_OPTIONS:
        fail(errors.ERR_OPTION_LIMIT_REACHED)
    for sibling in siblings:
        if sibling["speaker_id"] == speaker["id"]:
            fail(errors.ERR_DUPLICATE_SPEAKER_OPTION)
    for sibling in siblings:
        if sibling["rank_no"] == rank_no:
            fail(errors.ERR_DUPLICATE_RANK)

    if quoted_fee < speaker["fee_floor_cents"] or quoted_fee > speaker["fee_ceiling_cents"]:
        fail(errors.ERR_FEE_OUTSIDE_SPEAKER_RANGE)
    ceiling = calc.budget_ceiling_cents(inquiry["budget_cents"])
    if quoted_fee + travel_allowance > ceiling:
        fail(errors.ERR_QUOTE_EXCEEDS_BUDGET)

    option = new_row({
        "proposal_id": proposal["id"],
        "speaker_id": speaker["id"],
        "quoted_fee_cents": quoted_fee,
        "travel_allowance_cents": travel_allowance,
        "rank_no": rank_no,
        "status": "OFFERED",
    })
    db.options[option["id"]] = option
    proposal["options_count"] = proposal["options_count"] + 1
    touch(proposal)
    return ok(public(option), 201)


@bp.get("/proposal-options")
@roles("BureauAdmin", "BookingAgent", "Client")
def list_options():
    proposal_id = v.query_string("proposal_id")
    speaker_id = v.query_string("speaker_id")
    status = v.query_string("status")
    rows = []
    for row in db.options.values():
        if proposal_id is not None and row["proposal_id"] != proposal_id:
            continue
        if speaker_id is not None and row["speaker_id"] != speaker_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/proposal-options/<option_id>")
@roles("BureauAdmin", "BookingAgent", "Client")
def read_option(option_id):
    return ok(public(get_option(option_id)))


# --- negotiation ------------------------------------------------------------

def _expired(proposal):
    return db.now_utc() >= proposal["_valid_until_dt"]


@bp.post("/proposals/<proposal_id>/present")
@roles("BookingAgent")
def present_proposal(proposal_id):
    proposal = get_proposal(proposal_id)
    own_proposal(proposal)

    if proposal["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail(errors.ERR_PROPOSAL_STATE_INVALID)
    if _expired(proposal):
        fail(errors.ERR_PROPOSAL_EXPIRED)
    if proposal["options_count"] < 1:
        fail(errors.ERR_PROPOSAL_NO_OPTIONS)

    if proposal["status"] == "REVISION_REQUESTED":
        proposal["round_no"] = proposal["round_no"] + 1
    proposal["status"] = "PRESENTED"
    proposal["presented_at_utc"] = fmt_iso(db.now_utc())
    touch(proposal)

    inquiry = inquiry_of_proposal(proposal)
    if inquiry["status"] == "QUALIFIED":
        inquiry["status"] = "PROPOSED"
        touch(inquiry)
    return ok(public(proposal))


@bp.post("/proposals/<proposal_id>/request-revision")
@roles("Client")
def request_revision(proposal_id):
    proposal = get_proposal(proposal_id)
    data = v.body()
    v.opt_string(data, "revision_note")
    own_proposal(proposal)

    if proposal["status"] != "PRESENTED":
        fail(errors.ERR_PROPOSAL_STATE_INVALID)
    if _expired(proposal):
        fail(errors.ERR_PROPOSAL_EXPIRED)
    if proposal["revision_count"] >= calc.MAX_REVISION_ROUNDS:
        fail(errors.ERR_REVISION_LIMIT_REACHED)

    proposal["status"] = "REVISION_REQUESTED"
    proposal["revision_count"] = proposal["revision_count"] + 1
    touch(proposal)

    inquiry = inquiry_of_proposal(proposal)
    if inquiry["status"] == "PROPOSED":
        inquiry["status"] = "QUALIFIED"
        touch(inquiry)
    return ok(public(proposal))


@bp.post("/proposals/<proposal_id>/decline")
@roles("Client")
def decline_proposal(proposal_id):
    proposal = get_proposal(proposal_id)
    data = v.body()
    v.opt_string(data, "decline_reason")
    own_proposal(proposal)

    if proposal["status"] != "PRESENTED":
        fail(errors.ERR_PROPOSAL_STATE_INVALID)

    proposal["status"] = "DECLINED"
    for option in lifecycle.options_of(proposal["id"]):
        if option["status"] == "OFFERED":
            option["status"] = "REJECTED"
            touch(option)
    lifecycle.recount_options(proposal)
    touch(proposal)

    inquiry = inquiry_of_proposal(proposal)
    if inquiry["status"] == "PROPOSED":
        inquiry["status"] = "LOST"
        touch(inquiry)
    return ok(public(proposal))


@bp.post("/proposals/<proposal_id>/select")
@roles("Client")
def select_option(proposal_id):
    proposal = get_proposal(proposal_id)
    data = v.body()
    option_id = v.req_string(data, "option_id")
    option = get_option(option_id)

    own_proposal(proposal)

    if proposal["status"] != "PRESENTED":
        fail(errors.ERR_PROPOSAL_STATE_INVALID)
    if option["proposal_id"] != proposal["id"]:
        fail(errors.ERR_OPTION_NOT_IN_PROPOSAL)
    if option["status"] != "OFFERED":
        fail(errors.ERR_PROPOSAL_STATE_INVALID)

    inquiry = inquiry_of_proposal(proposal)
    client = db.clients[inquiry["client_id"]]
    if client["credit_status"] == "HOLD":
        fail(errors.ERR_CLIENT_CREDIT_HOLD)
    if _expired(proposal):
        fail(errors.ERR_PROPOSAL_EXPIRED)

    option["status"] = "SELECTED"
    touch(option)
    for sibling in lifecycle.options_of(proposal["id"]):
        if sibling["id"] != option["id"] and sibling["status"] == "OFFERED":
            sibling["status"] = "REJECTED"
            touch(sibling)
    lifecycle.recount_options(proposal)
    proposal["status"] = "ACCEPTED"
    touch(proposal)
    inquiry["status"] = "WON"
    touch(inquiry)

    engagement = new_row({
        "inquiry_id": inquiry["id"],
        "speaker_id": option["speaker_id"],
        "selected_option_id": option["id"],
        "owning_agent_user_id": inquiry["owning_agent_user_id"],
        "booking_status": "OFFERED",
        "settlement_status": "UNBILLED",
        "event_start_utc": inquiry["event_start_utc"],
        "event_end_utc": inquiry["event_end_utc"],
        "is_virtual": inquiry["is_virtual"],
        "quoted_fee_cents": option["quoted_fee_cents"],
        "travel_allowance_cents": option["travel_allowance_cents"],
        "recording_rights": "NONE",
        "recording_fee_cents": 0,
        "technical_rider_code": "STANDARD_AV",
        "commission_pct_snapshot": None,
        "provisional_commission_cents": None,
        "final_commission_cents": None,
        "travel_reimbursable_cents": 0,
        "cancelled_by": None,
        "cancellation_days_before": None,
        "retention_net_cents": None,
        "retention_commission_cents": None,
        "commission_adjustment_count": 0,
        "_event_start_dt": inquiry["_event_start_dt"],
        "_event_end_dt": inquiry["_event_end_dt"],
    })
    db.engagements[engagement["id"]] = engagement
    return ok(public(engagement), 201)
