"""Self-assessment and peer-review endpoints."""
from flask import Blueprint

from db import D, clock_date, new_entity, now_iso, parse_date, store, touch
from errors import ApiError
from middleware import authorize
from response import created, listing, ok
from routes.common import (by_created, filtered, find_assessment, find_cycle, find_partner,
                           find_review)
from services import calculations as calc
from services.engine import assessment_reviews, commit
from validation import (bad, field_decimal, field_enum, field_int, field_str, get_body,
                        pagination, query_enum, query_str)

bp = Blueprint("assessments", __name__)

READ_ROLES = ["CycleAdmin", "CommitteeMember", "Partner", "AuditObserver"]
DECISIONS = ["ACCEPT", "RETURN"]
OUTCOMES = ["SCORE", "RECUSE"]
REVIEW_WINDOW_STATES = ("SELF_ASSESSMENT", "PEER_REVIEW")


# =========================================================================
# SelfAssessment
# =========================================================================

@bp.post("/comp/self-assessments")
def create_assessment():
    user_id, _ = authorize(["Partner"])
    body = get_body()
    cycle_id = field_str(body, "cycle_id")
    narrative = field_str(body, "narrative")
    claimed_pct = field_decimal(body, "claimed_origination_pct_total", 2,
                                low="0.00", high="10000.00")
    claimed_hours = field_decimal(body, "claimed_non_billable_hours", 2, low="0.00")

    find_cycle(cycle_id)

    for existing in store.assessments.values():
        if existing["cycle_id"] == cycle_id and existing["partner_id"] == user_id:
            raise ApiError("ERR_DUPLICATE_ASSESSMENT")

    assessment = new_entity({
        "partner_id": user_id,
        "cycle_id": cycle_id,
        "narrative": narrative,
        "claimed_origination_pct_total": claimed_pct,
        "claimed_non_billable_hours": claimed_hours,
        "state": "DRAFT",
        "revision_count": 0,
        "returned_reason": None,
        "submitted_at": None,
        "accepted_at": None,
        "scored_review_count": 0,
        "mean_peer_score": D("0.0000"),
    })
    store.assessments[assessment["id"]] = assessment
    return created(commit(assessment))


@bp.get("/comp/self-assessments/<assessment_id>")
def read_assessment(assessment_id):
    authorize(READ_ROLES)
    return ok(find_assessment(assessment_id))


@bp.get("/comp/self-assessments")
def list_assessments():
    authorize(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "cycle_id": query_str("cycle_id"),
        "partner_id": query_str("partner_id"),
        "state": query_enum("state", calc.ASSESSMENT_STATES),
    }
    rows = by_created(filtered(store.assessments.values(), filters))
    return listing(rows, limit, offset)


@bp.post("/comp/self-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    user_id, _ = authorize(["Partner"])
    assessment = find_assessment(assessment_id)
    if user_id != assessment["partner_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if assessment["state"] != "DRAFT":
        raise ApiError("ERR_ASSESSMENT_NOT_MUTABLE")
    cycle = store.cycles[assessment["cycle_id"]]
    if cycle["state"] != "SELF_ASSESSMENT":
        raise ApiError("ERR_ASSESSMENT_WINDOW_CLOSED")
    if clock_date() > parse_date(cycle["assessment_deadline_on"]):
        raise ApiError("ERR_ASSESSMENT_WINDOW_CLOSED")
    assessment["state"] = "SUBMITTED"
    assessment["submitted_at"] = now_iso()
    touch(assessment)
    return ok(commit(assessment))


@bp.post("/comp/self-assessments/<assessment_id>/review-decision")
def review_decision(assessment_id):
    user_id, _ = authorize(["CommitteeMember"])
    body = get_body()
    decision = field_enum(body, "decision", DECISIONS)
    reason = field_str(body, "reason", required=False)
    if decision == "RETURN" and not reason:
        bad()

    assessment = find_assessment(assessment_id)
    if assessment["state"] != "SUBMITTED":
        raise ApiError("ERR_ASSESSMENT_NOT_REVIEWABLE")
    cycle = store.cycles[assessment["cycle_id"]]
    if cycle["state"] not in REVIEW_WINDOW_STATES:
        raise ApiError("ERR_REVIEW_WINDOW_CLOSED")
    if user_id == assessment["partner_id"]:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN")

    if decision == "ACCEPT":
        if assessment["scored_review_count"] < calc.MIN_SCORED_PEER_REVIEWS:
            raise ApiError("ERR_PEER_REVIEWS_INCOMPLETE")
        assessment["state"] = "ACCEPTED"
        assessment["accepted_at"] = now_iso()
    else:
        assessment["returned_reason"] = reason
        assessment["revision_count"] += 1
        assessment["state"] = "DRAFT"
        for review in assessment_reviews(assessment["id"]):
            if review["state"] != "SCORED":
                continue
            review["state"] = "ASSIGNED"
            review["technical_score"] = None
            review["collaboration_score"] = None
            review["client_service_score"] = None
            review["composite_score"] = None
            review["comment"] = None
            touch(review)
    touch(assessment)
    return ok(commit(assessment))


# =========================================================================
# PeerReview
# =========================================================================

@bp.post("/comp/peer-reviews")
def create_review():
    authorize(["CycleAdmin"])
    body = get_body()
    assessment_id = field_str(body, "self_assessment_id")
    reviewer_id = field_str(body, "reviewer_partner_id")

    assessment = find_assessment(assessment_id)
    find_partner(reviewer_id)

    if reviewer_id == assessment["partner_id"]:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN")

    for existing in store.reviews.values():
        if (existing["self_assessment_id"] == assessment_id
                and existing["reviewer_partner_id"] == reviewer_id):
            raise ApiError("ERR_DUPLICATE_REVIEW_ASSIGNMENT")

    review = new_entity({
        "self_assessment_id": assessment_id,
        "reviewer_partner_id": reviewer_id,
        "state": "ASSIGNED",
        "technical_score": None,
        "collaboration_score": None,
        "client_service_score": None,
        "composite_score": None,
        "comment": None,
        "recusal_reason": None,
    })
    store.reviews[review["id"]] = review
    return created(commit(review))


@bp.get("/comp/peer-reviews/<review_id>")
def read_review(review_id):
    authorize(READ_ROLES)
    return ok(find_review(review_id))


@bp.get("/comp/peer-reviews")
def list_reviews():
    authorize(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "self_assessment_id": query_str("self_assessment_id"),
        "reviewer_partner_id": query_str("reviewer_partner_id"),
        "state": query_enum("state", calc.REVIEW_STATES),
    }
    rows = by_created(filtered(store.reviews.values(), filters))
    return listing(rows, limit, offset)


@bp.post("/comp/peer-reviews/<review_id>/decide")
def decide_review(review_id):
    user_id, _ = authorize(["Partner"])
    body = get_body()
    outcome = field_enum(body, "outcome", OUTCOMES)
    technical = field_int(body, "technical_score", required=False, low=1, high=5)
    collaboration = field_int(body, "collaboration_score", required=False, low=1, high=5)
    client_service = field_int(body, "client_service_score", required=False, low=1, high=5)
    comment = field_str(body, "comment", required=False)
    recusal_reason = field_str(body, "recusal_reason", required=False)
    if outcome == "SCORE":
        if technical is None or collaboration is None or client_service is None:
            bad()
    elif not recusal_reason:
        bad()

    review = find_review(review_id)
    if user_id != review["reviewer_partner_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if review["state"] != "ASSIGNED":
        raise ApiError("ERR_REVIEW_ALREADY_DECIDED")

    assessment = store.assessments[review["self_assessment_id"]]
    if outcome == "SCORE":
        cycle = store.cycles[assessment["cycle_id"]]
        if cycle["state"] not in REVIEW_WINDOW_STATES:
            raise ApiError("ERR_REVIEW_WINDOW_CLOSED")
        if review["reviewer_partner_id"] == assessment["partner_id"]:
            raise ApiError("ERR_SELF_REVIEW_FORBIDDEN")
        review["technical_score"] = technical
        review["collaboration_score"] = collaboration
        review["client_service_score"] = client_service
        review["composite_score"] = calc.composite_score(technical, collaboration,
                                                         client_service)
        review["comment"] = comment
        review["state"] = "SCORED"
    else:
        review["recusal_reason"] = recusal_reason
        review["state"] = "RECUSED"
    touch(review)
    return ok(commit(review))
