"""Jurisdiction legal review cycle."""
from flask import Blueprint

import auth
import clock
import db
import services
import validate
import web
from errors import fail

bp = Blueprint("review", __name__)

REVIEW_READ = ["HRComplianceAdmin", "PolicyAuthor", "LegalCounsel"]


def _capacity_check(reviewer, candidate_start, candidate_end, exclude_id=None):
    used = services.reviewer_capacity_used(reviewer["id"], candidate_start, candidate_end, exclude_id)
    if used >= reviewer["concurrent_review_limit"]:
        fail("ERR_REVIEWER_CAPACITY_EXCEEDED", "reviewer occupation limit reached")


@bp.post("/policy-versions/<policy_version_id>/legal-reviews")
def create_review(policy_version_id):
    auth.authorize(["PolicyAuthor"])
    version = validate.path_row("policy_versions", policy_version_id)
    data = validate.body()
    if "jurisdiction_id" in data:
        validate.fk("jurisdictions", data.get("jurisdiction_id"))
    if "reviewer_id" in data:
        validate.fk("legal_reviewers", data.get("reviewer_id"))
    jurisdiction_id = validate.req_str(data, "jurisdiction_id")
    reviewer_id = validate.req_str(data, "reviewer_id")
    due_at = validate.req_datetime(data, "due_at")
    if version["status"] not in ("DRAFT", "IN_LEGAL_REVIEW"):
        fail("ERR_VERSION_INVALID_STATE", "version is %s" % version["status"])
    reviewer = db.get("legal_reviewers", reviewer_id)
    if not reviewer["is_active"]:
        fail("ERR_REVIEWER_INACTIVE", "reviewer is not active")
    for row in services.rows_where("legal_reviews", policy_version_id=version["id"],
                                   jurisdiction_id=jurisdiction_id):
        fail("ERR_DUPLICATE_RESOURCE", "a review already exists for this jurisdiction")
    now = clock.now()
    _capacity_check(reviewer, now, due_at)
    row = db.base_row()
    row.update({
        "policy_version_id": version["id"],
        "jurisdiction_id": jurisdiction_id,
        "reviewer_id": reviewer_id,
        "assigned_at": now,
        "due_at": due_at,
        "status": "REQUESTED",
        "decided_at": None,
        "round_no": 1,
        "comment": None,
    })
    db.insert("legal_reviews", row)
    services.adjust_open_reviews(reviewer, 1)
    return web.created("legal_reviews", row)


@bp.get("/legal-reviews")
def list_reviews():
    auth.authorize(REVIEW_READ)
    rows = db.all_rows("legal_reviews")
    rows = validate.query_filter(rows, "policy_version_id")
    rows = validate.query_filter(rows, "jurisdiction_id")
    rows = validate.query_filter(rows, "reviewer_id")
    rows = validate.query_filter(rows, "status")
    return web.paged("legal_reviews", rows)


@bp.get("/legal-reviews/<legal_review_id>")
def read_review(legal_review_id):
    auth.authorize(REVIEW_READ)
    row = validate.path_row("legal_reviews", legal_review_id)
    return web.one("legal_reviews", row)


@bp.post("/legal-reviews/<legal_review_id>/start")
def start_review(legal_review_id):
    actor = auth.authorize(["LegalCounsel"])
    review = validate.path_row("legal_reviews", legal_review_id)
    if review["reviewer_id"] != actor.user_id:
        fail("ERR_NOT_ASSIGNED_REVIEWER", "actor is not the assigned reviewer")
    if review["status"] != "REQUESTED":
        fail("ERR_REVIEW_INVALID_STATE", "review is %s" % review["status"])
    version = db.get("policy_versions", review["policy_version_id"])
    if version is None or version["status"] != "IN_LEGAL_REVIEW":
        fail("ERR_VERSION_INVALID_STATE", "owning version is not in legal review")
    review["status"] = "IN_PROGRESS"
    db.touch(review)
    return web.one("legal_reviews", review)


@bp.post("/legal-reviews/<legal_review_id>/decision")
def decide_review(legal_review_id):
    actor = auth.authorize(["LegalCounsel"])
    review = validate.path_row("legal_reviews", legal_review_id)
    data = validate.body()
    verdict = validate.req_enum(data, "verdict", ["APPROVE", "REQUEST_CHANGES"])
    if review["reviewer_id"] != actor.user_id:
        fail("ERR_NOT_ASSIGNED_REVIEWER", "actor is not the assigned reviewer")
    if review["status"] != "IN_PROGRESS":
        fail("ERR_REVIEW_INVALID_STATE", "review is %s" % review["status"])
    comment = data.get("comment")
    if verdict == "REQUEST_CHANGES":
        if not isinstance(comment, str) or not comment:
            fail("ERR_VALIDATION", "comment is required for a REQUEST_CHANGES verdict")
    elif comment is not None and not isinstance(comment, str):
        fail("ERR_VALIDATION", "comment must be a string")
    review["status"] = "APPROVED" if verdict == "APPROVE" else "CHANGES_REQUESTED"
    review["decided_at"] = clock.now()
    if comment is not None:
        review["comment"] = comment
    db.touch(review)
    reviewer = db.get("legal_reviewers", review["reviewer_id"])
    if reviewer is not None:
        services.adjust_open_reviews(reviewer, -1)
    if verdict == "REQUEST_CHANGES":
        version = db.get("policy_versions", review["policy_version_id"])
        if version is not None and version["status"] == "IN_LEGAL_REVIEW":
            services.revert_version_to_draft(version)
    return web.one("legal_reviews", review)


@bp.post("/legal-reviews/<legal_review_id>/re-request")
def rerequest_review(legal_review_id):
    auth.authorize(["PolicyAuthor"])
    review = validate.path_row("legal_reviews", legal_review_id)
    data = validate.body()
    due_at = validate.req_datetime(data, "due_at")
    if review["status"] != "CHANGES_REQUESTED":
        fail("ERR_REVIEW_INVALID_STATE", "review is %s" % review["status"])
    version = db.get("policy_versions", review["policy_version_id"])
    if version is None or version["status"] != "DRAFT":
        fail("ERR_VERSION_INVALID_STATE", "owning version is not in draft")
    reviewer = db.get("legal_reviewers", review["reviewer_id"])
    if reviewer is None or not reviewer["is_active"]:
        fail("ERR_REVIEWER_INACTIVE", "reviewer is not active")
    now = clock.now()
    _capacity_check(reviewer, now, due_at, exclude_id=review["id"])
    review["status"] = "REQUESTED"
    review["round_no"] = review["round_no"] + 1
    review["decided_at"] = None
    review["assigned_at"] = now
    review["due_at"] = due_at
    db.touch(review)
    services.adjust_open_reviews(reviewer, 1)
    return web.one("legal_reviews", review)
