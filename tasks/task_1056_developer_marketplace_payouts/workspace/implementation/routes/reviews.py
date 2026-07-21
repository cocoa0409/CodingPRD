"""Review submissions."""
from flask import Blueprint, g

from core import (
    authenticate,
    db,
    fail,
    filter_eq,
    get_body,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    public,
    req_enum,
    req_str,
    touch,
)
from services import lookup

bp = Blueprint("reviews", __name__)


@bp.get("/api/review-submissions")
def list_submissions():
    authenticate({"ReviewAgent", "PolicyOfficer", "PlatformAdmin", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.review_submissions)
    rows = filter_eq(rows, "app_id")
    rows = filter_eq(rows, "status")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/review-submissions/<review_submission_id>")
def read_submission(review_submission_id):
    authenticate({"ReviewAgent", "PolicyOfficer", "PlatformAdmin", "Developer"})
    sub = lookup("review_submissions", review_submission_id)
    return ok(public(sub))


@bp.post("/api/review-submissions/<review_submission_id>/triage")
def triage(review_submission_id):
    authenticate({"ReviewAgent"})
    sub = lookup("review_submissions", review_submission_id)
    if sub["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Submission is not SUBMITTED.")
    sub["status"] = "IN_TRIAGE"
    sub["triaged_by_user_id"] = g.user_id
    touch(sub)
    return ok(public(sub))


@bp.post("/api/review-submissions/<review_submission_id>/decision")
def decision(review_submission_id):
    authenticate({"ReviewAgent"})
    sub = lookup("review_submissions", review_submission_id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"PASSED", "REJECTED"})
    decision_reason = req_str(body, "decision_reason")
    if sub["status"] != "IN_TRIAGE":
        fail("ERR_INVALID_STATE", "Submission is not IN_TRIAGE.")
    app = db.apps.get(sub["app_id"])
    if app is None or app["status"] != "IN_REVIEW":
        fail("ERR_INVALID_STATE", "Listing is not IN_REVIEW.")
    sub["status"] = "PASSED" if outcome == "PASSED" else "REJECTED"
    sub["decision_reason"] = decision_reason
    touch(sub)
    app["status"] = "APPROVED" if outcome == "PASSED" else "CHANGES_REQUESTED"
    touch(app)
    return ok(public(sub))
