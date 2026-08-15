"""InpatientReview endpoints per PRD 3.8."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import (
    get_body,
    pagination_params,
    require_auth,
    require_role,
    validate_body,
)
from response import success_list, success_object
from serializers import serialize
from services import core
from services.calc import DRG_WEIGHTS, drg_payment, round_half_up_cents

bp = Blueprint("inpatient_reviews", __name__)
PREFIX = "/payment-integrity"

REVIEW_TYPES = {"DRG_VALIDATION", "READMISSION"}
REVIEW_STATUSES = {"OPEN", "FINDINGS_RECORDED", "DECIDED"}
OUTCOMES = {"NO_CHANGE", "DRG_REASSIGNED", "DENIED_READMISSION", "PARTIAL_REDUCTION"}


@bp.route(PREFIX + "/inpatient-reviews", methods=["GET"])
def list_inpatient_reviews():
    require_auth()
    limit, offset = pagination_params()
    claim_id = request.args.get("claim_id")
    prior_claim_id = request.args.get("prior_claim_id")
    review_type = request.args.get("review_type")
    status = request.args.get("status")
    rows = db.all_records("inpatient_reviews")
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if prior_claim_id is not None:
        rows = [r for r in rows if r.get("prior_claim_id") == prior_claim_id]
    if review_type is not None:
        if review_type not in REVIEW_TYPES:
            raise_err("ERR_INVALID_ENUM", "review_type filter carries undeclared member")
        rows = [r for r in rows if r["review_type"] == review_type]
    if status is not None:
        if status not in REVIEW_STATUSES:
            raise_err("ERR_INVALID_ENUM", "status filter carries undeclared member")
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return success_list([serialize(r) for r in rows[offset : offset + limit]], limit, offset, total)


def _get_review_or_404(rid):
    review = db.get("inpatient_reviews", rid)
    if review is None:
        raise_err("ERR_INPATIENT_REVIEW_NOT_FOUND", "Inpatient review not found")
    return review


@bp.route(PREFIX + "/inpatient-reviews/<rid>", methods=["GET"])
def get_inpatient_review(rid):
    require_auth()
    return success_object(serialize(_get_review_or_404(rid)))


@bp.route(PREFIX + "/inpatient-reviews/<rid>/record-findings", methods=["POST"])
def record_findings(rid):
    user_id, role = require_auth()
    require_role(role, ["SeniorReviewer"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "audited_drg_code": (False, "string", None),
            "findings_note": (False, "string", None),
        },
    )
    review = _get_review_or_404(rid)
    if review["status"] != "OPEN":
        raise_err("ERR_INPATIENT_REVIEW_NOT_DECIDABLE", "record-findings requires OPEN")
    # Band 11: audited DRG must be a known weight key when supplied
    audited = vals.get("audited_drg_code")
    if audited is not None and audited not in DRG_WEIGHTS:
        raise_err("ERR_DRG_CODE_UNKNOWN", "audited_drg_code not a known DRG weight key")
    review["status"] = "FINDINGS_RECORDED"
    if audited is not None:
        review["audited_drg_code"] = audited
    db.touch(review)
    return success_object(serialize(review))


@bp.route(PREFIX + "/inpatient-reviews/<rid>/decide", methods=["POST"])
def decide_inpatient_review(rid):
    user_id, role = require_auth()
    require_role(role, ["SeniorReviewer"])
    body = get_body()
    vals = validate_body(
        body,
        {
            "outcome": (True, "string", OUTCOMES),
            "decision_note": (False, "string", None),
        },
    )
    review = _get_review_or_404(rid)
    if review["status"] != "FINDINGS_RECORDED":
        raise_err("ERR_INPATIENT_REVIEW_NOT_DECIDABLE", "decide requires FINDINGS_RECORDED")
    outcome = vals["outcome"]
    audited = review.get("audited_drg_code")
    claim = db.get("claims", review["claim_id"])
    if outcome == "DRG_REASSIGNED":
        if audited is None or audited == review["provider_drg_code"]:
            raise_err(
                "ERR_INVALID_REQUEST",
                "DRG_REASSIGNED requires audited_drg_code != provider_drg_code",
            )
    if outcome == "DENIED_READMISSION":
        if review["review_type"] != "READMISSION":
            raise_err("ERR_INVALID_REQUEST", "DENIED_READMISSION requires a READMISSION review")
    if outcome == "PARTIAL_REDUCTION":
        if audited is None:
            raise_err("ERR_INVALID_REQUEST", "PARTIAL_REDUCTION requires audited_drg_code")

    review["status"] = "DECIDED"
    review["outcome"] = outcome

    if claim is not None:
        if outcome == "NO_CHANGE":
            review["payment_delta_cents"] = 0
        elif outcome == "DRG_REASSIGNED":
            new_payment = drg_payment(
                audited,
                claim["admission_date"],
                claim["discharge_date"],
                claim["discharge_disposition"],
            )
            old_baseline = claim["initial_allowed_cents"]
            delta = new_payment - old_baseline
            review["payment_delta_cents"] = delta
            claim["initial_allowed_cents"] = new_payment
            claim["allowed_amount_cents"] = max(0, claim["allowed_amount_cents"] + delta)
            claim["denied_amount_cents"] = claim["initial_allowed_cents"] - claim["allowed_amount_cents"]
        elif outcome == "DENIED_READMISSION":
            delta = -claim["allowed_amount_cents"]
            review["payment_delta_cents"] = delta
            claim["allowed_amount_cents"] = 0
            claim["denied_amount_cents"] = claim["initial_allowed_cents"]
        elif outcome == "PARTIAL_REDUCTION":
            provider_payment = drg_payment(
                review["provider_drg_code"],
                claim["admission_date"],
                claim["discharge_date"],
                claim["discharge_disposition"],
            )
            audited_payment = drg_payment(
                audited,
                claim["admission_date"],
                claim["discharge_date"],
                claim["discharge_disposition"],
            )
            reduction = round_half_up_cents(Decimal(provider_payment - audited_payment) / Decimal(2))
            delta = -reduction
            review["payment_delta_cents"] = delta
            claim["allowed_amount_cents"] = max(0, claim["allowed_amount_cents"] + delta)
            claim["denied_amount_cents"] = claim["initial_allowed_cents"] - claim["allowed_amount_cents"]
        db.touch(claim)
        core.claim_bubble_up(claim)
    db.touch(review)
    return success_object(serialize(review))
