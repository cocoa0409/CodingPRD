"""Reimbursement adjustment endpoints (PRD §3.8)."""

from flask import Blueprint

import calc
import config as C
import envelope
import models
import services
import validators
from auth import authenticate
from errors import ApiError
from routes.common import body_fk, listing, need
from store import db, ordered, touch

bp = Blueprint("adjustments", __name__)

ROLES = (C.ROLE_ANALYST, C.ROLE_SUPERVISOR)


@bp.post("/reimbursement-adjustments")
def create_adjustment():
    caller = authenticate(*ROLES)
    payload = validators.body()
    claim = body_fk(payload, "redemption_claim_id", db.redemption_claims, "ERR_CLAIM_NOT_FOUND")
    claim_id = validators.req_string(payload, "redemption_claim_id")
    reason_code = validators.req_enum(payload, "reason_code", C.ADJUSTMENT_REASON_CODES)
    rate = calc.dec(
        validators.req_number(payload, "recoupment_rate", exclusive_min=0, maximum=1)
    )
    expected = validators.req_int(payload, "expected_claim_version", minimum=0)

    if expected != claim["version"]:
        raise ApiError("ERR_STALE_CLAIM_VERSION")
    if claim["status"] == "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_ADJUDICATED")
    if claim["status"] == "PAID":
        raise ApiError("ERR_CLAIM_ALREADY_PAID")

    total, recoupments = calc.prorate_adjustment(claim, rate)
    payable = claim["net_payable_cents"] or 0
    if total > payable:
        raise ApiError("ERR_RECOUPMENT_EXCEEDS_PAYABLE")

    record = models.adjustment(
        redemption_claim_id=claim_id,
        reason_code=reason_code,
        recoupment_rate=rate,
        recoupment_cents=total,
        line_recoupments=recoupments,
        created_by_user_id=caller.user_id,
    )
    db.adjustments[record["id"]] = record
    touch(claim)
    return envelope.success(record, 201)


@bp.get("/reimbursement-adjustments/<entity_id>")
def read_adjustment(entity_id):
    authenticate(*ROLES)
    return envelope.success(need(db.adjustments, entity_id, "ERR_ADJUSTMENT_NOT_FOUND"))


@bp.get("/reimbursement-adjustments")
def list_adjustments():
    authenticate(*ROLES)
    return listing(
        ordered(db.adjustments),
        {"redemption_claim_id": "redemption_claim_id", "status": "status"},
    )


@bp.post("/reimbursement-adjustments/<entity_id>/apply")
def apply_adjustment(entity_id):
    caller = authenticate(C.ROLE_SUPERVISOR)
    adjustment = need(db.adjustments, entity_id, "ERR_ADJUSTMENT_NOT_FOUND")
    claim = db.redemption_claims.get(adjustment["redemption_claim_id"])
    if adjustment["status"] != "PENDING":
        raise ApiError("ERR_INVALID_ADJUSTMENT_STATE")
    if claim is not None and claim["status"] == "PAID":
        raise ApiError("ERR_CLAIM_ALREADY_PAID")
    if caller.user_id == adjustment["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if claim is None or claim["status"] != "ADJUDICATED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    if adjustment["recoupment_cents"] > (claim["net_payable_cents"] or 0):
        raise ApiError("ERR_RECOUPMENT_EXCEEDS_PAYABLE")

    vendor = db.vendors.get(claim["vendor_id"])
    services.apply_adjustment(adjustment, claim, vendor, caller.user_id)
    return envelope.success(adjustment)


@bp.post("/reimbursement-adjustments/<entity_id>/reverse")
def reverse_adjustment(entity_id):
    authenticate(C.ROLE_SUPERVISOR)
    adjustment = need(db.adjustments, entity_id, "ERR_ADJUSTMENT_NOT_FOUND")
    payload = validators.body()
    reason = validators.req_string(payload, "reversal_reason")
    claim = db.redemption_claims.get(adjustment["redemption_claim_id"])
    if adjustment["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_ADJUSTMENT_STATE")
    if claim is not None and claim["status"] == "PAID":
        raise ApiError("ERR_CLAIM_ALREADY_PAID")
    if claim is None or claim["status"] != "ADJUSTED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")

    vendor = db.vendors.get(claim["vendor_id"])
    services.reverse_adjustment(adjustment, claim, vendor, reason)
    return envelope.success(adjustment)
