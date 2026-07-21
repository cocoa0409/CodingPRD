"""Claim review, approval/disbursement, denial, withdrawal (PRD 3.6)."""
from flask import Blueprint, request, g

import db
from auth import require
from validation import get_or_404
from responses import success, list_response
from serializers import serialize
from errors import ApiError
from services import recompute_portfolio, terminate_agreements, append_ledger

bp = Blueprint("claims", __name__)


@bp.get("/claims/<cid>")
@require("Landlord", "ClaimsAdjuster", "Underwriter", "PlatformAdmin")
def get_claim(cid):
    c = get_or_404(db.claims, cid)
    return success(serialize(c), 200)


@bp.get("/claims")
@require("ClaimsAdjuster", "Underwriter", "PlatformAdmin", "Landlord")
def list_claims():
    args = request.args
    items = list(db.claims.values())
    for key in ("guarantee_id", "landlord_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    return list_response(items, args)


@bp.post("/claims/<cid>/review")
@require("ClaimsAdjuster")
def review_claim(cid):
    c = get_or_404(db.claims, cid)
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    c["status"] = "UNDER_REVIEW"
    db.touch(c)
    return success(serialize(c), 200)


@bp.post("/claims/<cid>/approve")
@require("ClaimsAdjuster")
def approve_claim(cid):
    c = get_or_404(db.claims, cid)
    guarantee = db.guarantees[c["guarantee_id"]]

    # segregation of duties (rank 5) precedes state (rank 7)
    if g.user_id == guarantee["underwritten_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    if guarantee["remaining_coverage_cents"] <= 0:
        raise ApiError("ERR_COVERAGE_EXHAUSTED")

    variant = "ACCELERATED" if c["acceleration_requested"] else "CHRONOLOGICAL"
    months = guarantee["coverage_months"] if variant == "ACCELERATED" else c["missed_months"]
    gross = guarantee["per_month_coverage_cents"] * months
    payout = min(gross, guarantee["remaining_coverage_cents"])

    c["payout_variant"] = variant
    c["payout_amount_cents"] = payout
    c["status"] = "PAID"  # APPROVED then immediate automatic disbursement
    db.touch(c)

    # cascade: debit coverage
    guarantee["remaining_coverage_cents"] -= payout
    guarantee["paid_out_cents"] += payout
    db.touch(guarantee)
    append_ledger(guarantee["id"], "CLAIM_PAYOUT", payout, "DEBIT",
                  guarantee["remaining_coverage_cents"])

    # cascade: recovery plan + applicant counter
    plan = {
        "claim_id": c["id"],
        "applicant_id": guarantee["applicant_id"],
        "principal_cents": payout,
        "recovered_cents": 0,
        "outstanding_cents": payout,
        "monthly_installment_cents": None,
        "status": "ACTIVE",
    }
    db.stamp_common(plan)
    db.recovery_plans[plan["id"]] = plan

    applicant = db.applicants[guarantee["applicant_id"]]
    applicant["open_recovery_count"] += 1
    db.touch(applicant)

    # automatic exhaustion
    if guarantee["remaining_coverage_cents"] == 0:
        guarantee["status"] = "EXHAUSTED"
        db.touch(guarantee)
        terminate_agreements(guarantee["id"], {"ACTIVE"})

    recompute_portfolio(db.portfolios[guarantee["portfolio_id"]])
    return success(serialize(c), 200)


@bp.post("/claims/<cid>/deny")
@require("ClaimsAdjuster")
def deny_claim(cid):
    c = get_or_404(db.claims, cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")
    c["status"] = "DENIED"
    db.touch(c)
    return success(serialize(c), 200)


@bp.post("/claims/<cid>/withdraw")
@require("Landlord")
def withdraw_claim(cid):
    c = get_or_404(db.claims, cid)
    if c["landlord_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if c["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE")
    c["status"] = "WITHDRAWN"
    db.touch(c)
    return success(serialize(c), 200)
