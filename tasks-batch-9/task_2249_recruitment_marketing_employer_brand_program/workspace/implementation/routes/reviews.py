"""Employer review monitoring, the response pipeline and brand health."""

from flask import Blueprint, g

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import calc, serialize

bp = Blueprint("reviews", __name__)

READ_ROLES = ("BrandProgramLead", "ComplianceReviewer", "CommunityManager",
              "RecruitingOps")
PLATFORMS = ("GLASSDOOR", "INDEED", "COMPARABLY")


def _resolve(review):
    """Freeze the SLA verdict at resolution time (PRD 3.8)."""
    review["responded_at"] = db.clock()
    review["sla_status"] = (
        "MET" if review["responded_at"] <= review["response_due_at"] else "BREACHED")


@bp.route("/employer-reviews", methods=["POST"])
@require("CommunityManager", "RecruitingOps")
def ingest_review():
    data = V.body()
    program_id = V.field(data, "program_id", "string", required=True)
    platform = V.field(data, "platform", "enum", required=True, values=PLATFORMS)
    external_ref = V.field(data, "external_ref", "string", required=True,
                           min_len=1, max_len=80)
    rating = V.field(data, "rating", "integer", required=True, min_value=1, max_value=5)
    posted_at = V.field(data, "posted_at", "datetime", required=True)
    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    for existing in db.reviews.values():
        if existing["platform"] == platform and existing["external_ref"] == external_ref:
            raise ApiError("ERR_DUPLICATE_REVIEW_REF",
                           "This external_ref already exists on %s." % platform)
    row = {
        "id": db.new_id(),
        "program_id": program["id"],
        "platform": platform,
        "external_ref": external_ref,
        "rating": rating,
        "posted_at": posted_at,
        "response_due_at": calc.review_response_deadline(posted_at, rating),
        "state": "NEW",
        # PRD 3.8 - "A new review is in `state` `NEW` with `sla_status` `PENDING`".
        "sla_status": "PENDING",
        "response_body": None,
        "rejection_count": 0,
        "drafted_by_user_id": None,
        "approved_by_user_id": None,
        "responded_at": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.reviews[row["id"]] = row
    # PRD 3.8 - "Ingesting a review immediately recomputes the program's
    # `brand_health_score`", which mutates the program (PRD 2.4).
    db.touch(program)
    return response.ok(serialize.review(row), 201)


@bp.route("/employer-reviews/<review_id>/triage", methods=["POST"])
@require("CommunityManager")
def triage_review(review_id):
    data = V.body()
    V.field(data, "note", "string", nullable=True, min_len=0, max_len=2000)
    review = calc.must_get(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    if review["state"] != "NEW":
        raise ApiError("ERR_REVIEW_NOT_NEW", "The review is not NEW.")
    review["state"] = "TRIAGED"
    # PRD 3.8 - "Triage re-evaluates `sla_status` against `response_due_at` and
    # the current logical clock."
    calc.reevaluate_sla(review)
    db.touch(review)
    return response.ok(serialize.review(review))


@bp.route("/employer-reviews/<review_id>/draft-response", methods=["POST"])
@require("CommunityManager")
def draft_response(review_id):
    data = V.body()
    body_text = V.field(data, "response_body", "string", required=True,
                        min_len=1, max_len=2000)
    review = calc.must_get(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    if review["state"] not in ("TRIAGED", "DRAFTING"):
        raise ApiError("ERR_REVIEW_NOT_DRAFTABLE", "The review is not draftable.")
    review["response_body"] = body_text
    review["drafted_by_user_id"] = g.user_id
    review["state"] = "DRAFTING"
    db.touch(review)
    return response.ok(serialize.review(review))


@bp.route("/employer-reviews/<review_id>/submit-legal", methods=["POST"])
@require("CommunityManager")
def submit_legal(review_id):
    review = calc.must_get(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    if review["state"] != "DRAFTING":
        raise ApiError("ERR_REVIEW_NOT_DRAFTING", "The review is not in DRAFTING.")
    if not review["response_body"]:
        raise ApiError("ERR_RESPONSE_BODY_MISSING", "No response_body is stored.")
    review["state"] = "LEGAL_REVIEW"
    db.touch(review)
    return response.ok(serialize.review(review))


@bp.route("/employer-reviews/<review_id>/legal-review", methods=["POST"])
@require("ComplianceReviewer")
def legal_review(review_id):
    data = V.body()
    decision = V.field(data, "decision", "enum", required=True,
                       values=("APPROVE", "REJECT"))
    V.field(data, "note", "string", nullable=True, min_len=0, max_len=2000)
    review = calc.must_get(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    if review["drafted_by_user_id"] is not None and g.user_id == review["drafted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The drafting user may not record the legal decision.")
    if review["state"] != "LEGAL_REVIEW":
        raise ApiError("ERR_REVIEW_NOT_IN_LEGAL_REVIEW",
                       "The review is not in LEGAL_REVIEW.")
    if decision == "APPROVE":
        review["state"] = "RESPONSE_PUBLISHED"
        review["approved_by_user_id"] = g.user_id
        _resolve(review)
        program = db.programs.get(review["program_id"])
        if program is not None:
            db.touch(program)
    else:
        review["state"] = "DRAFTING"
        review["rejection_count"] += 1
    db.touch(review)
    return response.ok(serialize.review(review))


@bp.route("/employer-reviews/<review_id>/close", methods=["POST"])
@require("CommunityManager")
def close_review(review_id):
    data = V.body()
    V.field(data, "note", "string", nullable=True, min_len=0, max_len=2000)
    review = calc.must_get(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    if review["state"] != "TRIAGED":
        raise ApiError("ERR_REVIEW_NOT_CLOSABLE", "The review is not closable.")
    if review["rating"] < 4:
        raise ApiError("ERR_RESPONSE_REQUIRED",
                       "A rating of 3 or below must receive a published response.")
    review["state"] = "CLOSED_NO_RESPONSE"
    _resolve(review)
    program = db.programs.get(review["program_id"])
    if program is not None:
        db.touch(program)
    db.touch(review)
    return response.ok(serialize.review(review))


@bp.route("/employer-reviews/<review_id>", methods=["GET"])
@require(*READ_ROLES)
def get_review(review_id):
    review = calc.must_get(db.reviews, review_id, "ERR_REVIEW_NOT_FOUND")
    return response.ok(serialize.review(review))


@bp.route("/employer-reviews", methods=["GET"])
@require(*READ_ROLES)
def list_reviews():
    limit, offset = V.pagination()
    rows = sorted(db.reviews.values(), key=lambda r: (r["posted_at"], r["created_at"]))
    for name in ("program_id", "platform", "state"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    sla = V.qs("sla_status")
    if sla:
        rows = [r for r in rows if calc.sla_status(r) == sla]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.review(r) for r in page], meta)
