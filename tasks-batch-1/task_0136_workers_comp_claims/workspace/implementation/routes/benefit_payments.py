"""BenefitPayment endpoints (PRD §3.6). TTD/TPD/PPD indemnity + reserve drawdown."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_RATING_NOT_FINALIZED,
    ERR_RESERVE_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, sort_and_page
from services.validation import require_str, require_int, require_enum
from services import calculations as calc
from services import reserve as reserve_svc
from routes._common import get_claim, get_benefit_payment, get_impairment_rating

bp = Blueprint("benefit_payments", __name__)

BENEFIT_TYPES = ["TTD", "TPD", "PPD"]


@bp.post("/benefit-payments")
def create_benefit_payment():
    require_auth(["ClaimsAdjuster"])()
    body = get_json_body()

    claim_id = require_str(body, "claim_id")
    claim = get_claim(claim_id)  # existence (priority 4)

    benefit_type = require_enum(body, "benefit_type", BENEFIT_TYPES)

    # Resolve any referenced impairment rating up front (existence, priority 4).
    rating = None
    rating_id = body.get("impairment_rating_id")
    if rating_id is not None:
        rating = get_impairment_rating(rating_id)

    weekly = reserve_svc.controlling_weekly_rate(claim_id)
    reserve = reserve_svc.reserve_for_claim(claim_id)

    # ---- compute amount per benefit_type ----
    if benefit_type == "TTD":
        amount = calc.indemnity_payment_ttd(weekly, claim["disability_days"])
    elif benefit_type == "TPD":
        # Field-shape (priority 14): TPD requires light_duty_weekly_cents.
        ld = body.get("light_duty_weekly_cents")
        if ld is None:
            raise APIError(ERR_INVALID_REQUEST, 400,
                           "light_duty_weekly_cents required for TPD")
        light_duty = require_int(body, "light_duty_weekly_cents", minimum=0)
        worker = db.workers.get(claim["worker_id"])
        aww = worker["average_weekly_wage_cents"] if worker else 0
        amount = calc.indemnity_payment_tpd(aww, light_duty, weekly)
    else:  # PPD
        # Field-shape (priority 14): PPD requires impairment_rating_id.
        if rating_id is None:
            raise APIError(ERR_INVALID_REQUEST, 400,
                           "impairment_rating_id required for PPD")
        # Rating-finalized safety guard (priority 8).
        if rating["status"] != "FINALIZED":
            raise APIError(ERR_RATING_NOT_FINALIZED, 409,
                           "PPD payment requires a FINALIZED impairment rating")
        amount = calc.indemnity_payment_ppd(rating["finalized_pct"], weekly)

    # Reserve sufficiency (priority 13): would-exceed boundary (equal is allowed).
    available = reserve["indemnity_reserve_cents"] if reserve else 0
    if amount > available:
        raise APIError(ERR_RESERVE_INSUFFICIENT, 422,
                       "Payment would exceed the outstanding indemnity reserve")

    payment = {
        "claim_id": claim_id,
        "benefit_type": benefit_type,
        "light_duty_weekly_cents": int(body.get("light_duty_weekly_cents") or 0),
        "impairment_rating_id": rating_id,
        "amount_cents": amount,
        "status": "POSTED",
    }
    db.stamp_common(payment)
    db.benefit_payments[payment["id"]] = payment

    # Draw down the reserve (conserved ledger).
    if reserve is not None:
        reserve_svc.apply_indemnity_payment(reserve, amount)

    # First TTD/TPD payment flips claim_class to LOST_TIME (PRD §3.6).
    if benefit_type in ("TTD", "TPD") and claim["claim_class"] != "LOST_TIME":
        claim["claim_class"] = "LOST_TIME"
        db.bump(claim)

    return ok_object(payment, 201)


@bp.get("/benefit-payments/<rid>")
def get_benefit_payment_route(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster"])()
    return ok_object(get_benefit_payment(rid), 200)


@bp.get("/claims/<rid>/benefit-payments")
def list_claim_benefit_payments(rid):
    require_auth(["PlatformAdmin", "ClaimsAdjuster"])()
    get_claim(rid)
    limit, offset = paginate_params(request.args)
    items = [p for p in db.benefit_payments.values() if p["claim_id"] == rid]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/benefit-payments")
def list_benefit_payments():
    require_auth(["PlatformAdmin", "ClaimsAdjuster"])()
    limit, offset = paginate_params(request.args)
    claim_id = request.args.get("claim_id")
    rating_id = request.args.get("impairment_rating_id")
    items = list(db.benefit_payments.values())
    if claim_id is not None:
        items = [p for p in items if p["claim_id"] == claim_id]
    if rating_id is not None:
        items = [p for p in items if p.get("impairment_rating_id") == rating_id]
    page, total = sort_and_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/benefit-payments/<rid>/void")
def void_benefit_payment(rid):
    require_auth(["ClaimsAdjuster"])()
    payment = get_benefit_payment(rid)
    if payment["status"] != "POSTED":
        raise APIError(ERR_INVALID_STATE, 409,
                       f"Cannot void a payment in status {payment['status']}")
    payment["status"] = "VOIDED"
    db.bump(payment)
    # Compensating reversal restores the indemnity reserve.
    reserve = reserve_svc.reserve_for_claim(payment["claim_id"])
    if reserve is not None:
        reserve_svc.reverse_indemnity_payment(reserve, payment["amount_cents"])
    return ok_object(payment, 200)
