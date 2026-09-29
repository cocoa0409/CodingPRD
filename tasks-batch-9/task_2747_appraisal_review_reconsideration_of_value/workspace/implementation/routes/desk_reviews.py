"""Desk review lifecycle: open, submit and decide."""

from flask import Blueprint

import db
import response
import validate as V
from errors import fail
from middleware import (ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE, ROLE_DESK_REVIEWER,
                        require_roles)
from routes.common import (PREFIX, body_fk, filter_equals, find_desk_review,
                           find_loan)
from services import constants as C
from services import escalation as esc_svc
from services import loans as loan_svc
from services import review as review_svc

bp = Blueprint("desk_reviews", __name__)


@bp.post(PREFIX + "/desk-reviews")
def open_desk_review():
    user_id, _ = require_roles(ROLE_DESK_REVIEWER)
    data = V.body()
    appraisal = body_fk(data, "appraisal_id", db.appraisals, "ERR_APPRAISAL_NOT_FOUND")
    V.req_str(data, "appraisal_id")
    reviewer_note = V.opt_str(data, "reviewer_note")
    expected = V.req_int(data, "expected_appraisal_version")

    if expected != appraisal["version"]:
        fail("ERR_STALE_VERSION")

    if appraisal["review_status"] not in ("RECEIVED", "RULES_CLEARED", "RULES_FLAGGED"):
        fail("ERR_INVALID_STATE")
    if review_svc.open_review_for(appraisal["id"]) is not None:
        fail("ERR_INVALID_STATE")
    if appraisal["review_status"] == "RECEIVED":
        fail("ERR_RULE_CHECKS_NOT_RUN")
    if appraisal["bias_screen_status"] == "NOT_SCREENED":
        fail("ERR_BIAS_SCREEN_REQUIRED")

    loan = find_loan(appraisal["loan_file_id"])
    record = db.make_record({
        "appraisal_id": appraisal["id"],
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "risk_tier_at_review": loan["risk_tier"],
        "preliminary_quality_score_bps": review_svc.preliminary_score(appraisal),
        "final_quality_score_bps": None,
        "required_escalation": None,
        "decision_action": None,
        "reviewer_note": reviewer_note,
        "findings_note": None,
        "decision_note": None,
    })
    db.desk_reviews[record["id"]] = record

    appraisal["review_status"] = "IN_DESK_REVIEW"
    db.bump(appraisal)
    loan["collateral_status"] = "UNDER_REVIEW"
    db.bump(loan)
    return response.created(record)


@bp.get(PREFIX + "/desk-reviews/<review_id>")
def get_desk_review(review_id):
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE)
    return response.ok(find_desk_review(review_id))


@bp.get(PREFIX + "/desk-reviews")
def list_desk_reviews():
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE)
    rows = db.ordered(db.desk_reviews)
    rows = filter_equals(rows, "appraisal_id")
    rows = filter_equals(rows, "status")
    return response.page(rows)


@bp.post(PREFIX + "/desk-reviews/<review_id>/submit")
def submit_desk_review(review_id):
    user_id, _ = require_roles(ROLE_DESK_REVIEWER)
    review = find_desk_review(review_id)
    data = V.body()
    findings_note = V.opt_str(data, "findings_note")

    if review["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    appraisal = db.appraisals.get(review["appraisal_id"])
    if appraisal["bias_screen_status"] == "NOT_SCREENED":
        fail("ERR_BIAS_SCREEN_REQUIRED")

    loan = find_loan(appraisal["loan_file_id"])
    score = review_svc.final_score(appraisal, loan)
    review["status"] = "SUBMITTED"
    review["submitted_by_user_id"] = user_id
    review["findings_note"] = findings_note
    review["final_quality_score_bps"] = score
    review["required_escalation"] = review_svc.required_escalation(
        appraisal, review["risk_tier_at_review"], score)
    db.bump(review)
    return response.ok(review)


@bp.post(PREFIX + "/desk-reviews/<review_id>/decide")
def decide_desk_review(review_id):
    user_id, _ = require_roles(ROLE_CHIEF_APPRAISER)
    review = find_desk_review(review_id)

    if review["submitted_by_user_id"] is not None and review["submitted_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    data = V.body()
    action = V.req_enum(data, "decision_action", C.DECISION_ACTIONS)
    decision_note = V.opt_str(data, "decision_note")

    if review["status"] != "SUBMITTED":
        fail("ERR_DESK_REVIEW_NOT_SUBMITTED")

    appraisal = db.appraisals.get(review["appraisal_id"])
    loan = find_loan(appraisal["loan_file_id"])
    required = review["required_escalation"]

    if action == "ACCEPT" and required != "NONE":
        fail("ERR_ESCALATION_REQUIRED")
    if action == "ESCALATE" and required == "NONE":
        fail("ERR_ESCALATION_REQUIRED")

    if loan_svc.appraisal_quarantined(appraisal):
        fail("ERR_BIAS_QUARANTINE_ACTIVE")
    if action == "ACCEPT" and appraisal["bias_screen_status"] in ("INDICATED", "SUBSTANTIATED"):
        fail("ERR_ESCALATION_REQUIRED")

    review["decided_by_user_id"] = user_id
    review["decision_action"] = action
    review["decision_note"] = decision_note

    if action == "ACCEPT":
        review["status"] = "ACCEPTED"
        db.bump(review)
        appraisal["review_status"] = "VALUE_ACCEPTED"
        db.bump(appraisal)
        loan["value_of_record_appraisal_id"] = appraisal["id"]
        loan["collateral_status"] = "VALUE_ACCEPTED"
        db.bump(loan)
        loan_svc.recompute_loan_values(loan)
    elif action == "ESCALATE":
        review["status"] = "ESCALATED"
        db.bump(review)
        appraisal["review_status"] = "ESCALATED"
        db.bump(appraisal)
        order = db.make_record({
            "desk_review_id": review["id"],
            "amc_id": appraisal["amc_id"],
            "assigned_appraiser_id": None,
            "escalation_type": required,
            "status": "PENDING_ASSIGNMENT",
            "due_at": None,
            "inspection_window_start": None,
            "inspection_window_end": None,
            "base_fee_cents": None,
            "rush_surcharge_cents": None,
            "discount_pct_bps": None,
            "total_cost_cents": None,
            "resulting_value_cents": None,
            "documentation_note": None,
            "cancel_reason": None,
        })
        order["due_at"] = db.hours_after(order["created_at"],
                                         esc_svc.turnaround_hours(required))
        db.escalation_orders[order["id"]] = order
    else:
        review["status"] = "RETURNED"
        db.bump(review)
        appraisal["review_status"] = "RETURNED_TO_AMC"
        db.bump(appraisal)

    return response.ok(review)
