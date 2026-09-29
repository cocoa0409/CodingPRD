"""Engagement booking track, delivery, cancellation and feedback (PRD §3.4 - §3.9)."""

from flask import Blueprint, g

import db
import errors
import validators as v
from errors import fail
from middleware import (
    client_of_engagement,
    get_engagement,
    inquiry_of_engagement,
    own_engagement,
    roles,
    speaker_of_engagement,
)
from response import ok, paged
from services import calc, lifecycle
from store import new_row, public, touch
from timeutil import add_days, fmt_iso, intervals_intersect_closed, whole_days

bp = Blueprint("engagements", __name__)

TERMINAL_BOOKING = (
    "DELIVERED",
    "DECLINED_BY_SPEAKER",
    "CANCELLED_BY_CLIENT",
    "CANCELLED_BY_SPEAKER",
)


# --- reads ------------------------------------------------------------------

@bp.get("/engagements")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def list_engagements():
    inquiry_id = v.query_string("inquiry_id")
    speaker_id = v.query_string("speaker_id")
    option_id = v.query_string("selected_option_id")
    booking_status = v.query_string("booking_status")
    settlement_status = v.query_string("settlement_status")
    rows = []
    for row in db.engagements.values():
        if inquiry_id is not None and row["inquiry_id"] != inquiry_id:
            continue
        if speaker_id is not None and row["speaker_id"] != speaker_id:
            continue
        if option_id is not None and row["selected_option_id"] != option_id:
            continue
        if booking_status is not None and row["booking_status"] != booking_status:
            continue
        if settlement_status is not None and row["settlement_status"] != settlement_status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/engagements/<engagement_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def read_engagement(engagement_id):
    return ok(public(get_engagement(engagement_id)))


# --- the speaker's answer ---------------------------------------------------

@bp.post("/engagements/<engagement_id>/confirm")
@roles("Speaker")
def confirm_engagement(engagement_id):
    engagement = get_engagement(engagement_id)
    own_engagement(engagement)

    if engagement["booking_status"] != "OFFERED":
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    speaker = speaker_of_engagement(engagement)
    if speaker["roster_status"] != "ACTIVE":
        fail(errors.ERR_SPEAKER_NOT_ACTIVE)

    lifecycle.sweep_expired_grants(db.now_utc())
    client = client_of_engagement(engagement)
    if lifecycle.exclusivity_conflict(engagement, client) is not None:
        fail(errors.ERR_EXCLUSIVITY_CONFLICT)

    buffer_days = speaker["travel_buffer_days"]
    hold_start = add_days(engagement["_event_start_dt"], -buffer_days)
    hold_end = add_days(engagement["_event_end_dt"], buffer_days)
    for existing in lifecycle.active_holds_for_speaker(speaker["id"]):
        if intervals_intersect_closed(hold_start, hold_end,
                                      existing["_start_dt"], existing["_end_dt"]):
            fail(errors.ERR_SPEAKER_CALENDAR_CONFLICT)

    engagement["booking_status"] = "CONFIRMED"
    touch(engagement)
    lifecycle.create_hold(speaker, "ENGAGEMENT", fmt_iso(hold_start), hold_start,
                          fmt_iso(hold_end), hold_end,
                          engagement_id=engagement["id"], reason=None)
    return ok(public(engagement))


@bp.post("/engagements/<engagement_id>/decline")
@roles("Speaker")
def decline_engagement(engagement_id):
    engagement = get_engagement(engagement_id)
    data = v.body()
    v.opt_string(data, "decline_reason")
    own_engagement(engagement)

    if engagement["booking_status"] != "OFFERED":
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    engagement["booking_status"] = "DECLINED_BY_SPEAKER"
    touch(engagement)

    option = db.options.get(engagement["selected_option_id"])
    if option is not None:
        if option["status"] == "SELECTED":
            option["status"] = "REJECTED"
            touch(option)
        proposal = db.proposals.get(option["proposal_id"])
        if proposal is not None:
            for sibling in lifecycle.options_of(proposal["id"]):
                if sibling["id"] != option["id"] and sibling["status"] == "REJECTED":
                    sibling["status"] = "OFFERED"
                    touch(sibling)
            lifecycle.recount_options(proposal)
            if proposal["status"] == "ACCEPTED":
                proposal["status"] = "PRESENTED"
            touch(proposal)

    inquiry = inquiry_of_engagement(engagement)
    if inquiry["status"] == "WON":
        inquiry["status"] = "PROPOSED"
        touch(inquiry)
    return ok(public(engagement))


# --- agreement drafting -----------------------------------------------------

@bp.post("/engagements/<engagement_id>/contracts")
@roles("BookingAgent")
def create_contract(engagement_id):
    engagement = get_engagement(engagement_id)
    data = v.body()
    schedule = v.req_enum(data, "cancellation_schedule_code", v.CANCELLATION_SCHEDULES)
    policy = v.req_enum(data, "travel_policy_code", v.TRAVEL_POLICIES)
    rights = v.req_enum(data, "recording_rights", v.RECORDING_RIGHTS)
    recording_fee = v.opt_cents(data, "recording_fee_cents", 0)
    rider = v.opt_enum(data, "technical_rider_code", v.TECHNICAL_RIDERS, "STANDARD_AV")
    exclusivity_days = v.opt_int(data, "exclusivity_days", 0)
    if exclusivity_days not in v.EXCLUSIVITY_DAYS:
        fail(errors.ERR_INVALID_REQUEST,
             "Field 'exclusivity_days' must be one of 0, 30, 90, 180.")

    own_engagement(engagement)

    if engagement["booking_status"] != "CONFIRMED":
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    if rights == "NONE":
        if recording_fee > 0:
            fail(errors.ERR_RECORDING_FEE_NOT_ALLOWED)
    elif recording_fee <= 0:
        fail(errors.ERR_RECORDING_FEE_REQUIRED)

    contract = new_row({
        "engagement_id": engagement["id"],
        "status": "DRAFT",
        "cancellation_schedule_code": schedule,
        "travel_policy_code": policy,
        "recording_rights": rights,
        "recording_fee_cents": recording_fee,
        "technical_rider_code": rider,
        "exclusivity_days": exclusivity_days,
        "speaker_signed_at_utc": None,
        "client_signed_at_utc": None,
        "executed_at_utc": None,
    })
    db.contracts[contract["id"]] = contract
    return ok(public(contract), 201)


# --- travel receipts --------------------------------------------------------

@bp.post("/engagements/<engagement_id>/travel-expenses")
@roles("Speaker", "BookingAgent")
def create_travel_expense(engagement_id):
    engagement = get_engagement(engagement_id)
    data = v.body()
    receipts = v.req_cents(data, "receipts_cents")
    travel_days = v.req_int(data, "travel_days", 1)
    band = v.req_enum(data, "distance_band", v.DISTANCE_BANDS)
    memo = v.opt_string(data, "memo")

    own_engagement(engagement)

    if engagement["booking_status"] not in ("CONFIRMED", "CONTRACTED"):
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    expense = new_row({
        "engagement_id": engagement["id"],
        "receipts_cents": receipts,
        "travel_days": travel_days,
        "distance_band": band,
        "memo": memo,
        "status": "SUBMITTED",
        "reimbursable_cents": None,
    })
    db.expenses[expense["id"]] = expense
    return ok(public(expense), 201)


# --- delivery ---------------------------------------------------------------

@bp.post("/engagements/<engagement_id>/deliver")
@roles("BookingAgent")
def deliver_engagement(engagement_id):
    engagement = get_engagement(engagement_id)
    own_engagement(engagement)

    if engagement["booking_status"] in TERMINAL_BOOKING:
        fail(errors.ERR_ENGAGEMENT_ALREADY_TERMINAL)
    if engagement["booking_status"] != "CONTRACTED":
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)
    if lifecycle.executed_contract(engagement["id"]) is None:
        fail(errors.ERR_CONTRACT_NOT_EXECUTED)
    now = db.now_utc()
    if now < engagement["_event_end_dt"]:
        fail(errors.ERR_EVENT_NOT_ENDED)

    engagement["booking_status"] = "DELIVERED"
    engagement["settlement_status"] = "INVOICED"
    engagement["final_commission_cents"] = calc.final_commission(
        engagement["quoted_fee_cents"],
        engagement["recording_fee_cents"],
        engagement["commission_pct_snapshot"],
    )
    touch(engagement)

    lifecycle.issue_invoice(engagement, "ENGAGEMENT_FEE", now)

    gross = engagement["quoted_fee_cents"] + engagement["recording_fee_cents"]
    lifecycle.create_remittance(engagement, gross,
                                engagement["final_commission_cents"],
                                engagement["travel_reimbursable_cents"])

    lifecycle.leave_calendar(engagement, "CONSUMED")

    speaker = speaker_of_engagement(engagement)
    speaker["engagements_delivered_count"] = speaker["engagements_delivered_count"] + 1
    speaker["lifetime_gross_fees_cents"] = speaker["lifetime_gross_fees_cents"] + gross
    touch(speaker)
    lifecycle.apply_roster_tier(speaker)
    return ok(public(engagement))


# --- cancellation -----------------------------------------------------------

@bp.post("/engagements/<engagement_id>/cancel")
@roles("Client", "Speaker", "BureauAdmin")
def cancel_engagement(engagement_id):
    engagement = get_engagement(engagement_id)
    data = v.body()
    v.opt_string(data, "cancellation_reason")
    if g.role == "BureauAdmin":
        side = v.req_enum(data, "on_behalf_of", ("CLIENT", "SPEAKER"))
    else:
        v.opt_enum(data, "on_behalf_of", ("CLIENT", "SPEAKER"))
        side = "CLIENT" if g.role == "Client" else "SPEAKER"

    own_engagement(engagement)

    if engagement["booking_status"] in TERMINAL_BOOKING:
        fail(errors.ERR_ENGAGEMENT_ALREADY_TERMINAL)
    if engagement["booking_status"] not in ("CONFIRMED", "CONTRACTED"):
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    prior = engagement["booking_status"]
    now = db.now_utc()
    engagement["cancelled_by"] = side
    engagement["cancellation_days_before"] = whole_days(engagement["_event_start_dt"], now)
    engagement["booking_status"] = (
        "CANCELLED_BY_CLIENT" if side == "CLIENT" else "CANCELLED_BY_SPEAKER"
    )
    touch(engagement)

    lifecycle.leave_calendar(engagement, "RELEASED")

    if side == "CLIENT" and prior == "CONTRACTED":
        contract = lifecycle.executed_contract(engagement["id"])
        schedule = contract["cancellation_schedule_code"] if contract else "STANDARD"
        net, commission = calc.cancellation_settlement(
            engagement["quoted_fee_cents"],
            schedule,
            engagement["cancellation_days_before"],
            engagement["commission_pct_snapshot"],
        )
        engagement["retention_net_cents"] = net
        engagement["retention_commission_cents"] = commission
        billable = net + engagement["travel_reimbursable_cents"]
        if billable > 0:
            engagement["settlement_status"] = "INVOICED"
            lifecycle.issue_invoice(engagement, "CANCELLATION_RETENTION", now)
            lifecycle.create_remittance(engagement, net, commission,
                                        engagement["travel_reimbursable_cents"])
        else:
            engagement["settlement_status"] = "WAIVED"
    else:
        engagement["settlement_status"] = "WAIVED"

    if side == "SPEAKER":
        speaker = speaker_of_engagement(engagement)
        if speaker["roster_status"] == "ACTIVE":
            speaker["roster_status"] = "PROBATION"
            touch(speaker)

    lifecycle.void_unexecuted_contracts(engagement["id"])
    lifecycle.expire_grants_of_engagement(engagement["id"])
    return ok(public(engagement))


# --- feedback ---------------------------------------------------------------

@bp.post("/engagements/<engagement_id>/feedback")
@roles("Client")
def create_feedback(engagement_id):
    engagement = get_engagement(engagement_id)
    data = v.body()
    content_score = v.req_int(data, "content_score", 1, 5)
    logistics_score = v.req_int(data, "logistics_score", 1, 5)
    rebook_intent = data.get("rebook_intent")
    if rebook_intent is not None and not isinstance(rebook_intent, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field 'rebook_intent' must be a boolean.")
    comment = v.opt_string(data, "comment")

    own_engagement(engagement)

    if engagement["booking_status"] != "DELIVERED":
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)
    for existing in db.feedbacks.values():
        if existing["engagement_id"] == engagement["id"]:
            fail(errors.ERR_FEEDBACK_ALREADY_SUBMITTED)
    if db.now_utc() < engagement["_event_end_dt"]:
        fail(errors.ERR_EVENT_NOT_ENDED)

    composite = calc.composite_score(content_score, logistics_score)
    feedback = new_row({
        "engagement_id": engagement["id"],
        "content_score": content_score,
        "logistics_score": logistics_score,
        "rebook_intent": rebook_intent,
        "comment": comment,
        "composite_score": float(composite),
    }, versioned=False)
    db.feedbacks[feedback["id"]] = feedback

    speaker = speaker_of_engagement(engagement)
    speaker["feedback_count"] = speaker["feedback_count"] + 1
    lifecycle.recompute_speaker_scores(speaker)
    lifecycle.apply_roster_tier(speaker)
    return ok(public(feedback), 201)


# --- commission adjustment (four-eyes) --------------------------------------

@bp.post("/engagements/<engagement_id>/commission-adjustments")
@roles("BookingAgent", "BureauAdmin")
def adjust_commission(engagement_id):
    engagement = get_engagement(engagement_id)
    data = v.body()
    expected_version = v.req_int(data, "expected_engagement_version")
    new_pct = v.req_number(data, "new_commission_pct")
    v.req_string(data, "reason")

    if engagement["owning_agent_user_id"] is not None \
            and g.user_id == engagement["owning_agent_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES)

    if expected_version != engagement["version"]:
        fail(errors.ERR_STALE_ENGAGEMENT_VERSION)

    if engagement["booking_status"] != "CONTRACTED":
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    pct = calc.dec(new_pct)
    if pct < calc.COMMISSION_PCT_MIN or pct > calc.COMMISSION_PCT_MAX:
        fail(errors.ERR_COMMISSION_PCT_OUT_OF_RANGE)

    engagement["commission_pct_snapshot"] = float(pct)
    engagement["provisional_commission_cents"] = calc.provisional_commission(
        engagement["quoted_fee_cents"], pct)
    engagement["commission_adjustment_count"] = engagement["commission_adjustment_count"] + 1
    touch(engagement)
    return ok(public(engagement))
