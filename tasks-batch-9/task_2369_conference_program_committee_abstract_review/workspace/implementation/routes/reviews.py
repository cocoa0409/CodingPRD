"""Review endpoints and discrepancy-case endpoints."""

from decimal import Decimal

from flask import Blueprint

from db import db, new_row, parse_dt, touch
from errors import fail
from middleware import ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER, endpoint
from response import ok, ok_list
from routes.helpers import filtered, lookup, resolve_fk
from services import calc, derive, logic
from validators import (body_json, paginate, q_bool, q_int, q_str, v_bool,
                        v_decimal, v_enum, v_int, v_string)

bp = Blueprint("reviews", __name__)

CONFIDENCE = ("LOW", "MEDIUM", "HIGH")
FORMATS = ("ORAL", "POSTER", "WORKSHOP")


@bp.get("/reviews")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def list_reviews(actor):
    rows = filtered(db.reviews.values(), {
        "abstract_id": q_str("abstract_id"),
        "reviewer_member_id": q_str("reviewer_member_id"),
        "status": q_str("status"),
        "assigned_round": q_int("assigned_round", None, 0, None),
        "is_third_review": q_bool("is_third_review"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.review_out(r) for r in page], meta)


@bp.get("/reviews/<review_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR, ROLE_REVIEWER)
def get_review(actor, review_id):
    row = lookup("reviews", review_id, "ERR_REVIEW_NOT_FOUND")
    return ok(derive.review_out(row))


@bp.post("/reviews/<review_id>/submission")
@endpoint(ROLE_REVIEWER, ROLE_CHAIR)
def submit_review(actor, review_id):
    review = lookup("reviews", review_id, "ERR_REVIEW_NOT_FOUND")
    abstract = db.abstracts.get(review["abstract_id"])
    conference = logic.conference_of(abstract) if abstract else None

    # Band 6 — only the assigned reviewer may file the review.
    if actor.member_id != review["reviewer_member_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    body = body_json()
    scores = {
        "originality": v_int(body, "score_originality", required=True, minimum=1, maximum=5),
        "methodology": v_int(body, "score_methodology", required=True, minimum=1, maximum=5),
        "relevance": v_int(body, "score_relevance", required=True, minimum=1, maximum=5),
        "clarity": v_int(body, "score_clarity", required=True, minimum=1, maximum=5),
    }
    confidence = v_enum(body, "confidence", CONFIDENCE, required=True)
    recommended_format = v_enum(body, "recommended_format", FORMATS, required=True)
    comments = v_string(body, "comments_to_authors", min_len=0, max_len=5000)

    # Band 9 / 10.
    if conference is None or conference["status"] != "REVIEW_OPEN":
        fail("ERR_CONFERENCE_STATE_INVALID", "Reviews are filed while review is open.")
    if review["status"] != "ASSIGNED":
        fail("ERR_REVIEW_STATE_INVALID")
    if review["assigned_round"] != abstract["revision_round"]:
        fail("ERR_REVIEW_STATE_INVALID",
             "This review belongs to a superseded revision round.")
    # Band 15.
    if db.now() > parse_dt(review["due_utc"]):
        fail("ERR_REVIEW_PAST_DUE")

    logic.apply_review_submission(review, abstract, scores, confidence,
                                  recommended_format, comments)
    return ok(derive.review_out(review))


@bp.post("/reviews/<review_id>/decline")
@endpoint(ROLE_REVIEWER, ROLE_CHAIR)
def decline_review(actor, review_id):
    review = lookup("reviews", review_id, "ERR_REVIEW_NOT_FOUND")
    abstract = db.abstracts.get(review["abstract_id"])
    conference = logic.conference_of(abstract) if abstract else None

    if actor.member_id != review["reviewer_member_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")

    body = body_json()
    decline_reason = v_string(body, "decline_reason", required=True, min_len=1, max_len=1000)
    auto_reassign = v_bool(body, "auto_reassign", default=True)

    if conference is None or conference["status"] != "REVIEW_OPEN":
        fail("ERR_CONFERENCE_STATE_INVALID")
    if review["status"] != "ASSIGNED":
        fail("ERR_REVIEW_STATE_INVALID")

    review["status"] = "DECLINED"
    review["decline_reason"] = decline_reason
    touch(review)
    logic.bump_member(db.members.get(review["reviewer_member_id"]))

    if auto_reassign:
        replacement = logic.select_reviewer(
            abstract, exclude={review["reviewer_member_id"]})
        if replacement is not None:
            logic.create_review(abstract, replacement, due_utc=review["due_utc"])
    return ok(derive.review_out(review))


# ---------------------------------------------------------------------------
# discrepancy cases
# ---------------------------------------------------------------------------

cases_bp = Blueprint("cases", __name__)


@cases_bp.get("/discrepancy-cases")
@endpoint(ROLE_ADMIN, ROLE_CHAIR)
def list_cases(actor):
    rows = filtered(db.cases.values(), {
        "abstract_id": q_str("abstract_id"),
        "arbiter_member_id": q_str("arbiter_member_id"),
        "third_review_id": q_str("third_review_id"),
        "status": q_str("status"),
    })
    page, meta = paginate(rows)
    return ok_list([derive.case_out(r) for r in page], meta)


@cases_bp.get("/discrepancy-cases/<case_id>")
@endpoint(ROLE_ADMIN, ROLE_CHAIR)
def get_case(actor, case_id):
    row = lookup("cases", case_id, "ERR_DISCREPANCY_CASE_NOT_FOUND")
    return ok(derive.case_out(row))


@cases_bp.post("/discrepancy-cases/<case_id>/arbiter")
@endpoint(ROLE_CHAIR)
def assign_arbiter(actor, case_id):
    case = lookup("cases", case_id, "ERR_DISCREPANCY_CASE_NOT_FOUND")
    abstract = db.abstracts.get(case["abstract_id"])
    body = body_json()
    arbiter = resolve_fk(body, "arbiter_member_id")
    if arbiter is None:
        fail("ERR_VALIDATION", "arbiter_member_id is required.")

    # Band 10.
    if case["status"] != "OPEN":
        fail("ERR_CASE_STATE_INVALID")
    if (arbiter["member_role"] != "CHAIR" or arbiter["status"] != "ACTIVE"
            or abstract is None
            or arbiter["conference_id"] != abstract["conference_id"]):
        fail("ERR_MEMBER_STATE_INVALID")
    # Band 11.
    for review in derive.abstract_reviews(abstract["id"]):
        if review["reviewer_member_id"] == arbiter["id"] and review["status"] == "SUBMITTED":
            fail("ERR_ARBITER_CONFLICT")
    if logic.member_has_conflict(arbiter["id"], abstract):
        fail("ERR_ARBITER_CONFLICT")

    case["arbiter_member_id"] = arbiter["id"]
    case["status"] = "ARBITER_ASSIGNED"
    touch(case)
    return ok(derive.case_out(case))


@cases_bp.post("/discrepancy-cases/<case_id>/resolution")
@endpoint(ROLE_CHAIR)
def resolve_case(actor, case_id):
    case = lookup("cases", case_id, "ERR_DISCREPANCY_CASE_NOT_FOUND")
    abstract = db.abstracts.get(case["abstract_id"])
    category = logic.category_of(abstract) if abstract else None

    # Band 6 — only the assigned arbiter may resolve.
    if case["arbiter_member_id"] != actor.member_id:
        fail("ERR_NOT_RESOURCE_OWNER")

    body = body_json()
    method = v_enum(body, "resolution_method", ("THIRD_REVIEW", "CHAIR_OVERRIDE"),
                    required=True)
    override_score = v_decimal(body, "override_score", minimum=Decimal("1.00"),
                               maximum=Decimal("5.50"))
    if method == "CHAIR_OVERRIDE":
        if override_score is None:
            fail("ERR_VALIDATION", "override_score is required for a chair override.")
        override_score = calc.round2(override_score)

    # Band 10.
    if case["status"] not in ("ARBITER_ASSIGNED", "ESCALATED"):
        fail("ERR_CASE_STATE_INVALID")
    if case["status"] == "ESCALATED" and method != "CHAIR_OVERRIDE":
        fail("ERR_CASE_STATE_INVALID",
             "An escalated case can only be closed by a chair override.")

    if method == "CHAIR_OVERRIDE":
        # Band 17 — the ceiling only applies from ARBITER_ASSIGNED.
        if case["status"] == "ARBITER_ASSIGNED":
            ceiling = category["discrepancy_threshold"] * Decimal("2")
            if not (case["spread_at_open"] < ceiling):
                fail("ERR_OVERRIDE_NOT_PERMITTED")
        case["status"] = "RESOLVED"
        case["resolution_method"] = "CHAIR_OVERRIDE"
        case["resolved_score"] = override_score
        touch(case)
        abstract["final_score"] = override_score
        logic.maybe_promote_to_scored(abstract)
        touch(abstract)
        return ok(derive.case_out(case))

    # THIRD_REVIEW — selector policy.
    exclude = {r["reviewer_member_id"] for r in derive.abstract_reviews(abstract["id"])}
    if case["arbiter_member_id"]:
        exclude.add(case["arbiter_member_id"])
    reviewer = logic.select_reviewer(abstract, exclude=exclude)
    if reviewer is None:
        fail("ERR_NO_ELIGIBLE_REVIEWER")
    review = logic.create_review(abstract, reviewer, is_third_review=True)
    case["status"] = "THIRD_REVIEW_PENDING"
    case["resolution_method"] = "THIRD_REVIEW"
    case["third_review_id"] = review["id"]
    touch(case)
    return ok(derive.case_out(case))
