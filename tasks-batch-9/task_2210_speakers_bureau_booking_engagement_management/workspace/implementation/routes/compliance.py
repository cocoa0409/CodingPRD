"""Exclusivity grants and non-circumvention claims (PRD §3.5, §3.9)."""

from flask import Blueprint

import db
import errors
import validators as v
from errors import fail
from middleware import get_claim, get_client, get_engagement, get_grant, get_speaker, roles
from response import ok, paged
from services import calc, lifecycle
from store import new_row, public, touch
from timeutil import whole_days

bp = Blueprint("compliance", __name__)


# --- exclusivity grants -----------------------------------------------------

@bp.get("/exclusivity-grants")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def list_grants():
    speaker_id = v.query_string("speaker_id")
    beneficiary = v.query_string("beneficiary_client_id")
    source = v.query_string("source_engagement_id")
    industry_code = v.query_string("industry_code")
    status = v.query_string("status")
    rows = []
    for row in db.grants.values():
        if speaker_id is not None and row["speaker_id"] != speaker_id:
            continue
        if beneficiary is not None and row["beneficiary_client_id"] != beneficiary:
            continue
        if source is not None and row["source_engagement_id"] != source:
            continue
        if industry_code is not None and row["industry_code"] != industry_code:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/exclusivity-grants/<grant_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def read_grant(grant_id):
    return ok(public(get_grant(grant_id)))


@bp.post("/exclusivity-grants/<grant_id>/waive")
@roles("BureauAdmin")
def waive_grant(grant_id):
    grant = get_grant(grant_id)
    data = v.body()
    v.opt_string(data, "waiver_reason")

    if grant["status"] != "ACTIVE":
        fail(errors.ERR_GRANT_NOT_ACTIVE)

    grant["status"] = "WAIVED"
    touch(grant)
    return ok(public(grant))


# --- circumvention claims ---------------------------------------------------

@bp.post("/circumvention-claims")
@roles("BureauAdmin", "BookingAgent")
def create_claim():
    data = v.body()
    client_id = v.req_string(data, "client_id")
    speaker_id = v.req_string(data, "speaker_id")
    source_id = v.req_string(data, "source_engagement_id")
    direct_raw, direct_dt = v.req_dt(data, "direct_event_date_utc")
    direct_fee = v.req_cents(data, "direct_fee_cents")

    client = get_client(client_id)
    speaker = get_speaker(speaker_id)
    source = get_engagement(source_id)

    if source["booking_status"] != "DELIVERED" \
            or source["commission_pct_snapshot"] is None:
        fail(errors.ERR_ENGAGEMENT_STATE_INVALID)

    days_after = whole_days(direct_dt, source["_event_end_dt"])
    factor = calc.protection_factor(days_after)
    if factor is None:
        fail(errors.ERR_OUTSIDE_PROTECTION_WINDOW)

    for existing in db.claims.values():
        if (existing["client_id"] == client["id"]
                and existing["speaker_id"] == speaker["id"]
                and existing["source_engagement_id"] == source["id"]
                and existing["status"] in ("OPEN", "UPHELD")):
            fail(errors.ERR_DUPLICATE_CLAIM)

    commission_due = calc.circumvention_commission_due(
        direct_fee, source["commission_pct_snapshot"], factor)

    claim = new_row({
        "client_id": client["id"],
        "speaker_id": speaker["id"],
        "source_engagement_id": source["id"],
        "direct_event_date_utc": direct_raw,
        "direct_fee_cents": direct_fee,
        "days_after_source": days_after,
        "protection_factor": float(factor),
        "commission_due_cents": commission_due,
        "status": "OPEN",
        "settled_cents": None,
    })
    db.claims[claim["id"]] = claim
    return ok(public(claim), 201)


@bp.get("/circumvention-claims")
@roles("BureauAdmin", "BookingAgent")
def list_claims():
    client_id = v.query_string("client_id")
    speaker_id = v.query_string("speaker_id")
    source = v.query_string("source_engagement_id")
    status = v.query_string("status")
    rows = []
    for row in db.claims.values():
        if client_id is not None and row["client_id"] != client_id:
            continue
        if speaker_id is not None and row["speaker_id"] != speaker_id:
            continue
        if source is not None and row["source_engagement_id"] != source:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/circumvention-claims/<claim_id>")
@roles("BureauAdmin", "BookingAgent")
def read_claim(claim_id):
    return ok(public(get_claim(claim_id)))


@bp.post("/circumvention-claims/<claim_id>/resolve")
@roles("BureauAdmin")
def resolve_claim(claim_id):
    claim = get_claim(claim_id)
    data = v.body()
    outcome = v.req_enum(data, "outcome", v.RESOLVE_OUTCOMES)
    v.opt_string(data, "resolution_note")
    settled_cents = None
    if outcome == "SETTLE":
        settled_cents = v.req_cents(data, "settled_cents")
    else:
        v.opt_cents(data, "settled_cents", None)

    if outcome == "SETTLE":
        if claim["status"] != "UPHELD":
            fail(errors.ERR_CLAIM_NOT_OPEN)
    elif claim["status"] != "OPEN":
        fail(errors.ERR_CLAIM_NOT_OPEN)

    if outcome == "SETTLE":
        if settled_cents > claim["commission_due_cents"]:
            fail(errors.ERR_INVALID_REQUEST,
                 "Field 'settled_cents' may not exceed the claim's commission_due_cents.")
        claim["status"] = "SETTLED"
        claim["settled_cents"] = settled_cents
        touch(claim)
        return ok(public(claim))

    if outcome == "DISMISS":
        claim["status"] = "DISMISSED"
        touch(claim)
        return ok(public(claim))

    claim["status"] = "UPHELD"
    touch(claim)

    client = db.clients[claim["client_id"]]
    client["circumvention_strikes"] = client["circumvention_strikes"] + 1
    if client["circumvention_strikes"] >= calc.CREDIT_HOLD_STRIKE_THRESHOLD:
        client["credit_status"] = "HOLD"
    touch(client)
    if client["credit_status"] == "HOLD":
        lifecycle.block_qualified_inquiries(client["id"])
    return ok(public(claim))
