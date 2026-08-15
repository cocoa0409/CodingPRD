"""AfterActionReview endpoints (PRD 3.7)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_AAR_EXISTS, ERR_VALIDATION,
    ERR_SELF_APPROVAL_FORBIDDEN,
)
from middleware import authorized, ALL_ROLES, ROLE_OFFICER, ROLE_PRINCIPAL
from response import success_object
from services.core import new_record, public, apply_changes
from validate import get_body, reject_unknown, req_enum, req_str, opt_str
from routes.helpers import get_path, list_query

bp = Blueprint("reviews", __name__)

RATINGS = ["EXCEEDS", "MEETS", "NEEDS_IMPROVEMENT", "UNSATISFACTORY"]
EVAC_ASSESSMENTS = ["MET_STANDARD", "MET_ADJUSTED", "NOT_MET"]


@bp.post("/drill-events/<rid>/after-action-reviews")
def create_review(rid):
    authorized([ROLE_OFFICER])
    drill = get_path("drill_events", rid)
    body = get_body()
    reject_unknown(body, ["findings_summary", "overall_rating", "evacuation_assessment"])
    findings = req_str(body, "findings_summary")
    rating = req_enum(body, "overall_rating", RATINGS)
    evac = req_enum(body, "evacuation_assessment", EVAC_ASSESSMENTS)

    # priority 5: drill must be COMPLETED
    if drill["status"] != "COMPLETED":
        raise_error(ERR_INVALID_STATE,
                    "an after-action review may only open on a COMPLETED drill")

    # priority 9: at most one review per drill
    for a in db["after_action_reviews"].values():
        if a["drill_event_id"] == drill["id"]:
            raise_error(ERR_AAR_EXISTS, "drill already has an after-action review")

    rec = new_record("after_action_reviews", {
        "drill_event_id": drill["id"],
        "findings_summary": findings,
        "overall_rating": rating,
        "evacuation_assessment": evac,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "decided_by_user_id": None,
        "return_reason": None,
        "ca_total_count": 0,
        "ca_verified_count": 0,
    })
    return success_object(public(rec), 201)


@bp.get("/drill-events/<rid>/after-action-reviews")
def list_reviews(rid):
    authorized(ALL_ROLES)
    get_path("drill_events", rid)
    return list_query("after_action_reviews", {"drill_event_id": rid})


@bp.get("/after-action-reviews/<rid>")
def get_review(rid):
    authorized(ALL_ROLES)
    rec = get_path("after_action_reviews", rid)
    return success_object(public(rec))


@bp.post("/after-action-reviews/<rid>/submit")
def submit_review(rid):
    caller = authorized([ROLE_OFFICER])
    aar = get_path("after_action_reviews", rid)
    body = get_body()
    reject_unknown(body, [])

    if aar["status"] not in ("DRAFT", "RETURNED"):
        raise_error(ERR_INVALID_STATE, "review must be DRAFT or RETURNED to submit")

    apply_changes(aar, {
        "status": "SUBMITTED",
        "submitted_by_user_id": caller.user_id,
        "return_reason": None,
    })
    return success_object(public(aar))


@bp.post("/after-action-reviews/<rid>/decide")
def decide_review(rid):
    caller = authorized([ROLE_PRINCIPAL])
    aar = get_path("after_action_reviews", rid)
    body = get_body()
    reject_unknown(body, ["decision", "return_reason"])
    decision = req_enum(body, "decision", ["ACCEPT", "RETURN"])
    return_reason = opt_str(body, "return_reason")
    if decision == "RETURN" and (return_reason is None or return_reason.strip() == ""):
        raise_error(ERR_VALIDATION, "return_reason is required when decision is RETURN")

    if aar["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "review must be SUBMITTED to decide")

    # priority 9: self-approval forbidden
    if caller.user_id == aar["submitted_by_user_id"]:
        raise_error(ERR_SELF_APPROVAL_FORBIDDEN,
                    "decider must differ from the review's submitter")

    if decision == "ACCEPT":
        apply_changes(aar, {
            "status": "ACCEPTED",
            "decided_by_user_id": caller.user_id,
        })
    else:
        apply_changes(aar, {
            "status": "RETURNED",
            "decided_by_user_id": caller.user_id,
            "return_reason": return_reason,
        })
    return success_object(public(aar))
