"""Claim endpoints (PRD §3.4): intake, adjudicate, pay, reverse, reads."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_CROSS_PLAN_REFERENCE,
    ERR_INVALID_DATE_RANGE, ERR_AMOUNT_OUT_OF_RANGE,
)
from middleware import authorized
from response import success_object
from routes.helpers import READ_ALL, get_one, list_response
from services.accumulation import check_window_ambiguity, sweep_for_claim
from services.core import new_record, public, touch
from util import norm_dt, parse_dt
from validate import (
    get_body, req_str, req_int, req_enum, req_datetime,
    require_path_resource, require_ref,
)

bp = Blueprint("claims", __name__)

CLAIM_TYPES = {"MEDICAL", "RX"}
# Filings in these statuses pin their line-item claims against reversal.
REVERSAL_BLOCKING_FILING_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "APPROVED", "PAID")


@bp.post("/stop-loss/claims")
def create_claim():
    authorized(["ClaimsExaminer"])
    body = get_body()
    plan_id = req_str(body, "plan_id")
    member_id = req_str(body, "member_id")
    service_date = req_datetime(body, "service_date")
    billed = req_int(body, "billed_amount_cents", minimum=0)
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)

    require_ref("plans", plan_id, "plan_id")
    member = require_ref("members", member_id, "member_id")
    # Intake checks run in a fixed order (PRD §3.4): cross-plan first.
    if member["plan_id"] != plan_id:
        raise_error(ERR_CROSS_PLAN_REFERENCE,
                    "member_id does not belong to the plan named on the claim")
    # The service_date <= paid_date temporal check cannot fire at intake:
    # paid_date stays null until the claim is paid.

    rec = new_record("claims", {
        "plan_id": plan_id,
        "member_id": member_id,
        "service_date": norm_dt(service_date),
        "paid_date": None,
        "billed_amount_cents": billed,
        "allowed_amount_cents": None,
        "paid_amount_cents": None,
        "claim_type": claim_type,
        "status": "SUBMITTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/stop-loss/claims/<rid>")
def get_claim(rid):
    return get_one("claims", rid, READ_ALL)


@bp.get("/stop-loss/claims")
def list_claims():
    return list_response("claims", READ_ALL, {
        "plan_id": request.args.get("plan_id"),
        "member_id": request.args.get("member_id"),
        "status": request.args.get("status"),
    })


@bp.post("/stop-loss/claims/<rid>/adjudicate")
def adjudicate_claim(rid):
    authorized(["ClaimsExaminer"])
    body = get_body()
    allowed = req_int(body, "allowed_amount_cents", minimum=0)
    claim = require_path_resource("claims", rid)
    if claim["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"claim in {claim['status']} cannot be adjudicated")
    if allowed > claim["billed_amount_cents"]:
        raise_error(ERR_AMOUNT_OUT_OF_RANGE,
                    "allowed_amount_cents may not exceed billed_amount_cents")
    claim["allowed_amount_cents"] = allowed
    touch(claim)
    claim["status"] = "ADJUDICATED"
    return success_object(public(claim))


@bp.post("/stop-loss/claims/<rid>/pay")
def pay_claim(rid):
    authorized(["ClaimsExaminer"])
    body = get_body()
    paid = req_int(body, "paid_amount_cents", minimum=0)
    paid_date = req_datetime(body, "paid_date")
    claim = require_path_resource("claims", rid)
    if claim["status"] != "ADJUDICATED":
        raise_error(ERR_INVALID_STATE,
                    f"claim in {claim['status']} cannot be paid")
    # Business checks in validation-priority order: date range (6), window
    # ambiguity (7), amount bounds (10).
    if parse_dt(claim["service_date"]) > parse_dt(paid_date):
        raise_error(ERR_INVALID_DATE_RANGE,
                    "service_date must not fall after paid_date")
    probe = dict(claim)
    probe["paid_date"] = norm_dt(paid_date)
    check_window_ambiguity(claim["plan_id"], probe)
    if paid > claim["allowed_amount_cents"]:
        raise_error(ERR_AMOUNT_OUT_OF_RANGE,
                    "paid_amount_cents may not exceed allowed_amount_cents")

    claim["paid_amount_cents"] = paid
    claim["paid_date"] = norm_dt(paid_date)
    touch(claim)
    claim["status"] = "PAID"
    # Immediate consistency: recompute the affected ledgers before responding.
    sweep_for_claim(claim)
    return success_object(public(claim))


@bp.post("/stop-loss/claims/<rid>/reverse")
def reverse_claim(rid):
    authorized(["ClaimsExaminer"])
    get_body()
    claim = require_path_resource("claims", rid)
    if claim["status"] != "PAID":
        raise_error(ERR_INVALID_STATE,
                    f"claim in {claim['status']} cannot be reversed")
    # A claim pinned by an active filing line item cannot be reversed; DRAFT and
    # DISPUTED filings do not block the unwind (PRD §3.4).
    for line in db["line_items"].values():
        if line["claim_id"] != claim["id"]:
            continue
        filing = db["filings"].get(line["filing_id"])
        if filing is not None and filing["status"] in REVERSAL_BLOCKING_FILING_STATUSES:
            raise_error(ERR_INVALID_STATE,
                        "claim is referenced by a filing in an active status")
    touch(claim)
    claim["status"] = "REVERSED"
    sweep_for_claim(claim)
    return success_object(public(claim))
