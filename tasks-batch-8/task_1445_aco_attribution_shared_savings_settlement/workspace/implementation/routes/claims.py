"""Claim lines and high-cost reviews."""
from flask import Blueprint, request

import db
from errors import (ApiError, not_found, ERR_PERIOD_NOT_OPEN,
                    ERR_BENEFICIARY_OPTED_OUT, ERR_DATE_OUTSIDE_PERIOD,
                    ERR_CLAIM_INVALID_STATE, ERR_REVIEW_NOT_FLAGGED)
from middleware import (require_roles, ROLE_ACO_ADMIN, ROLE_CLAIMS,
                        ROLE_MRO, ROLE_ACTUARY, ALL_DOMAIN_ROLES)
from response import success, list_success
from serializers import claim_out, high_cost_review_out
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("claims", __name__)

CLAIM_SPEC = {
    "agreement_period_id": {"type": "string", "required": True},
    "beneficiary_id": {"type": "string", "required": True},
    "participant_id": {"type": "string", "required": False},
    "service_date": {"type": "date", "required": True},
    "allowed_amount_cents": {"type": "int", "required": True, "min": 1},
    "claim_type": {"type": "enum", "enum": ["PART_A", "PART_B"], "required": True},
}

VOID_SPEC = {
    "reason": {"type": "string", "required": False},
}

DETERMINE_SPEC = {
    "outcome": {"type": "enum", "enum": ["CONFIRMED_EXCLUSION", "DISMISSED"],
                "required": True},
    "rationale": {"type": "string", "required": False},
}

REVIEW_READ_ROLES = [ROLE_ACO_ADMIN, ROLE_CLAIMS, ROLE_MRO, ROLE_ACTUARY]


@bp.post("/aco/claims")
def create_claim():
    require_roles([ROLE_CLAIMS])
    body = validate_body(get_json_body(), CLAIM_SPEC)
    # Reference resolution (priority 4), in declared FK order.
    period = db.periods.get(body["agreement_period_id"])
    if period is None:
        raise not_found("Agreement period not found")
    beneficiary = db.beneficiaries.get(body["beneficiary_id"])
    if beneficiary is None:
        raise not_found("Beneficiary not found")
    participant_id = body.get("participant_id")
    if participant_id is not None and participant_id not in db.participants:
        raise not_found("Participant not found")
    # Period posture (priority 6).
    if period["status"] != "OPEN":
        raise ApiError(ERR_PERIOD_NOT_OPEN, 409,
                       "Claim ingestion requires an OPEN period")
    # Privacy gate (priority 9): latest election with effective_date <= the
    # claim's service_date decides.
    if calc.opted_out_as_of(beneficiary["id"], body["service_date"]):
        raise ApiError(ERR_BENEFICIARY_OPTED_OUT, 422,
                       "Beneficiary is opted out as of the service date")
    # Temporal placement (priority 11): closed performance span.
    if not (period["performance_start_date"] <= body["service_date"]
            <= period["performance_end_date"]):
        raise ApiError(ERR_DATE_OUTSIDE_PERIOD, 422,
                       "service_date lies outside the performance period")
    claim = db.stamp_new({
        "id": db.new_id(),
        "agreement_period_id": period["id"],
        "beneficiary_id": beneficiary["id"],
        "participant_id": participant_id,
        "service_date": body["service_date"],
        "allowed_amount_cents": body["allowed_amount_cents"],
        "claim_type": body["claim_type"],
        "review_excluded": False,
        "status": "RECEIVED",
    })
    db.claims[claim["id"]] = claim
    return success(claim_out(claim), 201)


@bp.get("/aco/claims/<claim_id>")
def get_claim(claim_id):
    require_roles(ALL_DOMAIN_ROLES)
    claim = db.claims.get(claim_id)
    if claim is None:
        raise not_found("Claim not found")
    return success(claim_out(claim))


@bp.get("/aco/claims")
def list_claims():
    require_roles(ALL_DOMAIN_ROLES)
    items = list(db.claims.values())
    for param in ("agreement_period_id", "beneficiary_id", "participant_id",
                  "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    items.sort(key=lambda c: c["created_at"])
    return list_success([claim_out(c) for c in items])


@bp.post("/aco/claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    require_roles([ROLE_CLAIMS])
    get_json_body()
    claim = db.claims.get(claim_id)
    if claim is None:
        raise not_found("Claim not found")
    # Period posture (priority 6) precedes entity state (priority 7).
    period = db.periods[claim["agreement_period_id"]]
    if period["status"] != "OPEN":
        raise ApiError(ERR_PERIOD_NOT_OPEN, 409,
                       "Adjudication requires an OPEN period")
    if claim["status"] != "RECEIVED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, 409,
                       "Adjudicate requires the claim to be RECEIVED")
    claim["status"] = "ADJUDICATED"
    db.bump(claim)
    # High-cost claimant watch fires on adjudication (YTD includes this claim).
    calc.maybe_flag_high_cost(claim["beneficiary_id"], claim["agreement_period_id"])
    return success(claim_out(claim))


@bp.post("/aco/claims/<claim_id>/void")
def void_claim(claim_id):
    require_roles([ROLE_CLAIMS])
    validate_body(get_json_body(), VOID_SPEC)
    claim = db.claims.get(claim_id)
    if claim is None:
        raise not_found("Claim not found")
    if claim["status"] != "ADJUDICATED":
        raise ApiError(ERR_CLAIM_INVALID_STATE, 409,
                       "Void requires the claim to be ADJUDICATED")
    claim["status"] = "VOIDED"
    db.bump(claim)
    # Auto-dismiss a flagged review whose YTD fell back below the threshold.
    calc.maybe_dismiss_high_cost(claim["beneficiary_id"],
                                 claim["agreement_period_id"])
    # Voiding changes the expenditure basis: stale any PROPOSED settlement.
    calc.stale_proposed_settlements(claim["agreement_period_id"])
    return success(claim_out(claim))


# ---------------------------------------------------------------------------
# High-cost reviews
# ---------------------------------------------------------------------------
@bp.get("/aco/high-cost-reviews/<review_id>")
def get_review(review_id):
    require_roles(REVIEW_READ_ROLES)
    review = db.high_cost_reviews.get(review_id)
    if review is None:
        raise not_found("High-cost review not found")
    return success(high_cost_review_out(review))


@bp.get("/aco/high-cost-reviews")
def list_reviews():
    require_roles(REVIEW_READ_ROLES)
    items = list(db.high_cost_reviews.values())
    for param in ("agreement_period_id", "beneficiary_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    items.sort(key=lambda r: r["created_at"])
    return list_success([high_cost_review_out(r) for r in items])


@bp.post("/aco/high-cost-reviews/<review_id>/determine")
def determine_review(review_id):
    uid, _ = require_roles([ROLE_MRO])
    body = validate_body(get_json_body(), DETERMINE_SPEC)
    review = db.high_cost_reviews.get(review_id)
    if review is None:
        raise not_found("High-cost review not found")
    if review["status"] != "FLAGGED":
        raise ApiError(ERR_REVIEW_NOT_FLAGGED, 409,
                       "Determine requires the review to be FLAGGED")
    outcome = body["outcome"]
    review["status"] = outcome
    review["determined_by_user_id"] = uid
    if "rationale" in body:
        review["rationale"] = body["rationale"]
    if outcome == "CONFIRMED_EXCLUSION":
        # Sweep the beneficiary's ADJUDICATED claims of the period out of the
        # expenditure input set.
        for c in db.claims.values():
            if (c["agreement_period_id"] == review["agreement_period_id"]
                    and c["beneficiary_id"] == review["beneficiary_id"]
                    and c["status"] == "ADJUDICATED"
                    and not c["review_excluded"]):
                c["review_excluded"] = True
                db.bump(c)
        calc.stale_proposed_settlements(review["agreement_period_id"])
    else:
        review["dismissal_reason"] = "MANUAL"
    db.bump(review)
    return success(high_cost_review_out(review))
