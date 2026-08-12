"""Continuing-activity reviews (90-day cycle)."""
from datetime import timedelta

from flask import Blueprint

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body
from util import REVIEW_OUTCOMES, base_entity, req_enum, serialize, touch

bp = Blueprint("reviews", __name__)


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


@bp.route("/continuing-reviews/<rid>", methods=["GET"])
def get_review(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    review = _get(db.reviews, rid, "ContinuingReview")
    return response.success(serialize(review), status=200)


@bp.route("/continuing-reviews/<rid>/start", methods=["POST"])
def start_review(rid):
    _, role = authn()
    authz(role, ["BSAAnalyst"])
    review = _get(db.reviews, rid, "ContinuingReview")
    if review["status"] not in {"SCHEDULED", "OVERDUE"}:
        raise ApiError("ERR_INVALID_STATE",
                       f"Review in status {review['status']} cannot be started", 409)
    review["status"] = "IN_PROGRESS"
    touch(review)
    return response.success(serialize(review), status=200)


@bp.route("/continuing-reviews/<rid>/complete", methods=["POST"])
def complete_review(rid):
    body = get_body()
    outcome = req_enum(body, "outcome", REVIEW_OUTCOMES)
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    review = _get(db.reviews, rid, "ContinuingReview")
    if review["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE",
                       f"Review in status {review['status']} cannot be completed", 409)
    sar = _get(db.sars, review["sar_report_id"], "SARReport")
    if sar["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE",
                       "Reviewed SAR is no longer FILED", 409)
    review["outcome"] = outcome
    review["completed_at"] = db.now()
    review["status"] = "COMPLETED"
    touch(review)

    if outcome == "FILE_CONTINUING_SAR":
        new_sar = base_entity()
        new_sar.update({
            "case_id": sar["case_id"],
            "customer_id": sar["customer_id"],
            "prior_sar_id": sar["id"],
            "is_continuing": True,
            "subject_unidentified": False,
            "narrative": "",
            "narrative_length": 0,
            "activity_start_date": sar["activity_end_date"] + timedelta(days=1),
            "activity_end_date": sar["activity_end_date"] + timedelta(days=90),
            "deadline_at": review["filing_deadline_at"],
            "status": "DRAFT",
            "drafted_by_analyst_id": user_id,
            "qa_reviewer_id": None,
            "approved_by_analyst_id": None,
            "filed_at": None,
            "filing_reference": None,
        })
        db.sars[new_sar["id"]] = new_sar
        review["created_continuing_sar_id"] = new_sar["id"]
        case = db.cases.get(sar["case_id"])
        if case is not None and case["status"] == "CLOSED":
            case["status"] = "SAR_IN_PROGRESS"
            case["closed_reason"] = None
            case["closed_at"] = None
            case["decision"] = "SAR_REQUIRED"
            touch(case)
            assignee = db.analysts.get(case["assigned_analyst_id"])
            if assignee is not None:
                assignee["assigned_open_cases"] += 1
                touch(assignee)
    return response.success(serialize(review), status=200)
