"""The two-step fraud review lifecycle."""

from flask import Blueprint

from db import bump, db, now
from errors import ApiError
from middleware import authorize
from response import object_response
from timeutils import plus_minutes
from validation import opt_string, payload, req_enum
from services import fraud, lookup, serializers
from services.constants import ACK_SLA_MINUTES, FRAUD_BLOCK_THRESHOLD, FRAUD_DECISIONS

bp = Blueprint("fraud_reviews", __name__)


@bp.route("/fraud-reviews/<review_id>/assignment", methods=["POST"])
def assign_review(review_id):
    user_id, _role = authorize(["FraudReviewer"])
    review = lookup.fraud_review(review_id)
    transfer = lookup.credit_transfer(review["credit_transfer_id"])
    if review["status"] != "QUEUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a QUEUED review may be taken.")
    if transfer["clearing_status"] != "FRAUD_HOLD":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The reviewed transfer is no longer held.")
    if user_id == transfer["initiated_by_user_id"]:
        raise ApiError(
            "ERR_FRAUD_SEGREGATION_OF_DUTIES",
            "An operator may not review its own origination.",
        )
    review["status"] = "UNDER_REVIEW"
    review["assigned_reviewer_user_id"] = user_id
    review["sla_deadline_at"] = plus_minutes(now(), ACK_SLA_MINUTES)
    bump(review)
    return object_response(serializers.fraud_review(review))


@bp.route("/fraud-reviews/<review_id>/decision", methods=["POST"])
def decide_review(review_id):
    user_id, _role = authorize(["FraudReviewer"])
    review = lookup.fraud_review(review_id)
    transfer = lookup.credit_transfer(review["credit_transfer_id"])
    body = payload()
    decision = req_enum(body, "decision", FRAUD_DECISIONS)
    rationale = opt_string(body, "decision_rationale")

    if review["status"] == "QUEUED":
        raise ApiError(
            "ERR_FRAUD_REVIEW_NOT_ASSIGNED",
            "The review must be taken before it can be decided.",
        )
    if review["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The review has already been decided.")
    if user_id == transfer["initiated_by_user_id"]:
        raise ApiError(
            "ERR_FRAUD_SEGREGATION_OF_DUTIES",
            "An operator may not decide its own origination.",
        )
    if user_id != review["assigned_reviewer_user_id"]:
        raise ApiError(
            "ERR_FRAUD_SEGREGATION_OF_DUTIES",
            "Only the assigned reviewer may decide this item.",
        )

    customer = lookup.customer_account(transfer["customer_account_id"])
    final_score = fraud.score_at_review(customer, transfer)

    if decision == "RELEASE":
        if final_score >= FRAUD_BLOCK_THRESHOLD:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The recomputed fraud score is at or above the block threshold.",
            )
        review["status"] = "RELEASED"
        review["final_fraud_score"] = final_score
        review["decision_rationale"] = rationale
        bump(review)
        transfer["clearing_status"] = "INITIATED"
        bump(transfer)
        return object_response(serializers.fraud_review(review))

    review["status"] = "BLOCKED"
    review["final_fraud_score"] = final_score
    review["decision_rationale"] = rationale
    bump(review)
    transfer["clearing_status"] = "REJECTED"
    transfer["rejection_reason_code"] = "FRAUD_BLOCK_REVIEW"
    bump(transfer)
    customer["status"] = "RESTRICTED"
    customer["restricted_at"] = now()
    bump(customer)
    instant = now()
    for row in sorted(db.credit_transfers.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if row["id"] == transfer["id"]:
            continue
        if row["customer_account_id"] != customer["id"]:
            continue
        if row["clearing_status"] != "INITIATED":
            continue
        row["clearing_status"] = "QUEUED_THROTTLED"
        row["queued_at"] = instant
        bump(row)
    return object_response(serializers.fraud_review(review))
