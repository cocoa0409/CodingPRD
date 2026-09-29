"""Roster, client register and speaker calendar (PRD §3.1, §3.2)."""

from flask import Blueprint, request

import db
import errors
import validators as v
from errors import fail
from middleware import get_client, get_hold, get_speaker, roles
from response import ok, paged
from services import calc, lifecycle
from store import new_row, public, touch
from timeutil import intervals_intersect_closed

bp = Blueprint("roster", __name__)


# --- speakers ---------------------------------------------------------------

@bp.post("/speakers")
@roles("BureauAdmin")
def create_speaker():
    data = v.body()
    full_name = v.req_string(data, "full_name", 1, 120)
    topics = v.req_code_list(data, "topics", v.TOPIC_CODES, 1, 5)
    fee_floor = v.req_cents(data, "fee_floor_cents")
    fee_ceiling = v.req_cents(data, "fee_ceiling_cents")
    if fee_ceiling < fee_floor:
        fail(errors.ERR_INVALID_REQUEST,
             "fee_ceiling_cents must be greater than or equal to fee_floor_cents.")
    travel_class = v.req_enum(data, "travel_class", v.TRAVEL_CLASSES)
    travel_buffer_days = v.opt_int(data, "travel_buffer_days", 1, 0, 3)
    tax_form_status = v.opt_enum(data, "tax_form_status", v.TAX_FORM_STATUSES, "MISSING")

    speaker = new_row({
        "full_name": full_name,
        "topics": topics,
        "fee_floor_cents": fee_floor,
        "fee_ceiling_cents": fee_ceiling,
        "travel_class": travel_class,
        "travel_buffer_days": travel_buffer_days,
        "roster_status": "ACTIVE",
        "tax_form_status": tax_form_status,
        "roster_tier": "BRONZE",
        "default_commission_pct": float(calc.TIER_COMMISSION_PCT["BRONZE"]),
        "engagements_delivered_count": 0,
        "lifetime_gross_fees_cents": 0,
        "held_days_count": 0,
        "pending_remittance_cents": 0,
        "rolling_score": None,
        "lifetime_score": None,
        "feedback_count": 0,
    })
    db.speakers[speaker["id"]] = speaker
    return ok(public(speaker), 201)


@bp.get("/speakers")
@roles("BureauAdmin", "BookingAgent")
def list_speakers():
    topic = v.query_string("topic")
    roster_status = v.query_string("roster_status")
    roster_tier = v.query_string("roster_tier")
    rows = []
    for row in db.speakers.values():
        if topic is not None and topic not in row["topics"]:
            continue
        if roster_status is not None and row["roster_status"] != roster_status:
            continue
        if roster_tier is not None and row["roster_tier"] != roster_tier:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/speakers/<speaker_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def read_speaker(speaker_id):
    return ok(public(get_speaker(speaker_id)))


@bp.patch("/speakers/<speaker_id>")
@roles("BureauAdmin")
def patch_speaker(speaker_id):
    speaker = get_speaker(speaker_id)
    data = v.body()
    roster_status = v.opt_enum(data, "roster_status", v.ROSTER_STATUSES)
    tax_form_status = v.opt_enum(data, "tax_form_status", v.TAX_FORM_STATUSES)
    fee_floor = v.opt_int(data, "fee_floor_cents", None, 0)
    fee_ceiling = v.opt_int(data, "fee_ceiling_cents", None, 0)
    travel_class = v.opt_enum(data, "travel_class", v.TRAVEL_CLASSES)
    travel_buffer_days = v.opt_int(data, "travel_buffer_days", None, 0, 3)

    new_floor = speaker["fee_floor_cents"] if fee_floor is None else fee_floor
    new_ceiling = speaker["fee_ceiling_cents"] if fee_ceiling is None else fee_ceiling
    if new_ceiling < new_floor:
        fail(errors.ERR_INVALID_REQUEST,
             "fee_ceiling_cents must be greater than or equal to fee_floor_cents.")

    if roster_status is not None:
        speaker["roster_status"] = roster_status
    if tax_form_status is not None:
        speaker["tax_form_status"] = tax_form_status
    speaker["fee_floor_cents"] = new_floor
    speaker["fee_ceiling_cents"] = new_ceiling
    if travel_class is not None:
        speaker["travel_class"] = travel_class
    if travel_buffer_days is not None:
        speaker["travel_buffer_days"] = travel_buffer_days
    touch(speaker)
    return ok(public(speaker))


@bp.get("/speakers/<speaker_id>/performance")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def read_performance(speaker_id):
    speaker = get_speaker(speaker_id)
    variant = request.args.get("variant")
    if variant is None or variant == "":
        variant = "ROLLING"
    if variant not in v.PERFORMANCE_VARIANTS:
        fail(errors.ERR_INVALID_REQUEST,
             "Query parameter 'variant' must be one of ROLLING, LIFETIME.")
    score = speaker["rolling_score"] if variant == "ROLLING" else speaker["lifetime_score"]
    return ok({
        "speaker_id": speaker["id"],
        "variant": variant,
        "score": score,
        "feedback_count": speaker["feedback_count"],
        "roster_tier": speaker["roster_tier"],
        "default_commission_pct": speaker["default_commission_pct"],
    })


# --- clients ----------------------------------------------------------------

@bp.post("/clients")
@roles("BureauAdmin")
def create_client():
    data = v.body()
    org_name = v.req_string(data, "org_name", 1, 160)
    industry_code = v.req_enum(data, "industry_code", v.INDUSTRY_CODES)
    email = v.req_string(data, "primary_contact_email", 1)

    row = new_row({
        "org_name": org_name,
        "industry_code": industry_code,
        "primary_contact_email": email,
        "credit_status": "GOOD",
        "outstanding_balance_cents": 0,
        "circumvention_strikes": 0,
    })
    db.clients[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/clients")
@roles("BureauAdmin", "BookingAgent")
def list_clients():
    industry_code = v.query_string("industry_code")
    credit_status = v.query_string("credit_status")
    rows = []
    for row in db.clients.values():
        if industry_code is not None and row["industry_code"] != industry_code:
            continue
        if credit_status is not None and row["credit_status"] != credit_status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/clients/<client_id>")
@roles("BureauAdmin", "BookingAgent", "Client")
def read_client(client_id):
    return ok(public(get_client(client_id)))


@bp.patch("/clients/<client_id>")
@roles("BureauAdmin")
def patch_client(client_id):
    row = get_client(client_id)
    data = v.body()
    credit_status = v.opt_enum(data, "credit_status", v.CREDIT_STATUSES)
    email = v.opt_string(data, "primary_contact_email")

    if credit_status is not None:
        row["credit_status"] = credit_status
    if email is not None:
        row["primary_contact_email"] = email
    touch(row)
    if credit_status in ("GOOD", "WATCH"):
        lifecycle.unblock_inquiries(row["id"])
    return ok(public(row))


# --- speaker calendar -------------------------------------------------------

@bp.post("/speaker-holds")
@roles("BureauAdmin", "BookingAgent")
def create_hold():
    data = v.body()
    speaker_id = v.req_string(data, "speaker_id")
    start_raw, start_dt = v.req_dt(data, "hold_start_utc")
    end_raw, end_dt = v.req_dt(data, "hold_end_utc")
    reason = v.opt_string(data, "reason")

    speaker = get_speaker(speaker_id)

    for existing in lifecycle.active_holds_for_speaker(speaker["id"]):
        if intervals_intersect_closed(start_dt, end_dt,
                                      existing["_start_dt"], existing["_end_dt"]):
            fail(errors.ERR_SPEAKER_CALENDAR_CONFLICT)

    hold = lifecycle.create_hold(speaker, "BLACKOUT", start_raw, start_dt,
                                 end_raw, end_dt, engagement_id=None, reason=reason)
    return ok(public(hold), 201)


@bp.get("/speaker-holds")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def list_holds():
    speaker_id = v.query_string("speaker_id")
    engagement_id = v.query_string("engagement_id")
    kind = v.query_string("kind")
    status = v.query_string("status")
    rows = []
    for row in db.holds.values():
        if speaker_id is not None and row["speaker_id"] != speaker_id:
            continue
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            continue
        if kind is not None and row["kind"] != kind:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/speaker-holds/<hold_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker")
def read_hold(hold_id):
    return ok(public(get_hold(hold_id)))
