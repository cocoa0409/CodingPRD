"""Review drafting, submission, moderation and revision."""

from flask import Blueprint

import clock
import db as store
import serializers
from db import db, new_row, ordered, touch
from errors import ApiError
from middleware import acting_user_id, endpoint
from response import collection, single
from services import calculations as calc
from services.gates import (must_exist, require_campaign_status, require_not_banned,
                            require_owner, require_segregation)
from validation import field, paginate, parse_body, parse_query

bp = Blueprint("review_submissions", __name__)

REVIEW_STATUSES = ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "DISCLOSURE_REJECTED",
                   "APPROVED", "RETRACTED")
DECISIONS = ("APPROVE", "REQUEST_CHANGES", "REJECT_DISCLOSURE")
REVIEW_CAMPAIGN_STATUSES = ("SAMPLING_ACTIVE", "REVIEW_WINDOW")

CREATE_FIELDS = [
    field("enrollment_id", "id", required=True),
    field("headline", "string", required=True, max_length=120),
    field("body_text", "string", required=True),
    field("star_rating", "integer", required=True, minimum=1, maximum=5),
    field("disclosure_statement", "string"),
    field("honest_opinion_attested", "boolean", default=False),
]

REVISE_FIELDS = [
    field("headline", "string", required=True, max_length=120),
    field("body_text", "string", required=True),
    field("star_rating", "integer", required=True, minimum=1, maximum=5),
    field("disclosure_statement", "string"),
    field("honest_opinion_attested", "boolean"),
]

MODERATE_FIELDS = [
    field("decision", "enum", required=True, values=DECISIONS),
    field("moderator_note", "string"),
]

LIST_FILTERS = [
    field("enrollment_id", "string"),
    field("status", "enum", values=REVIEW_STATUSES),
]


def _content_gates(review, campaign):
    """Ladder rungs 18, 19 and 22 in ladder order."""
    if not review["honest_opinion_attested"]:
        raise ApiError("ERR_HONEST_OPINION_NOT_ATTESTED",
                       "The honest-opinion attestation is required")
    if not calc.disclosure_present(review["disclosure_statement"]):
        raise ApiError("ERR_DISCLOSURE_STATEMENT_MISSING",
                       "The disclosure statement must contain an accepted "
                       "incentivized-review phrase")
    if review["word_count"] < campaign["min_review_word_count"]:
        raise ApiError("ERR_REVIEW_TOO_SHORT",
                       "The review has %d words but %d are required"
                       % (review["word_count"], campaign["min_review_word_count"]))


@bp.post("/review-submissions")
@endpoint(["Panelist"])
def create_review():
    body, _ = parse_body(CREATE_FIELDS)
    enrollment = must_exist("enrollments", body["enrollment_id"], "Enrollment")
    require_owner(enrollment["panelist_id"])
    campaign = store.campaign_of_enrollment(enrollment)
    require_campaign_status(campaign, REVIEW_CAMPAIGN_STATUSES)
    require_not_banned(store.panelist_of_enrollment(enrollment))

    row = new_row()
    row.update({
        "enrollment_id": enrollment["id"],
        "headline": body["headline"],
        "body_text": body["body_text"],
        "star_rating": body["star_rating"],
        "disclosure_statement": body["disclosure_statement"],
        "honest_opinion_attested": bool(body["honest_opinion_attested"]),
        "word_count": calc.word_count(body["body_text"]),
        "status": "DRAFT",
        "revision_count": 0,
        "first_submitted_at": None,
        "changes_requested_by_user_id": None,
        "approved_by_user_id": None,
        "moderator_note": None,
    })
    db.review_submissions[row["id"]] = row
    return single(serializers.review_submission(row), 201)


@bp.get("/review-submissions/<review_submission_id>")
@endpoint(["ComplianceModerator", "CampaignManager", "Panelist", "PlatformAdmin"])
def get_review(review_submission_id):
    parse_body([])
    row = must_exist("review_submissions", review_submission_id, "Review")
    enrollment = store.enrollment_of_review(row)
    if enrollment is not None:
        require_owner(enrollment["panelist_id"])
    return single(serializers.review_submission(row))


@bp.get("/review-submissions")
@endpoint(["ComplianceModerator", "CampaignManager", "PlatformAdmin"])
def list_reviews():
    query = parse_query(LIST_FILTERS)
    rows = ordered(db.review_submissions.values())
    if query["enrollment_id"] is not None:
        rows = [r for r in rows if r["enrollment_id"] == query["enrollment_id"]]
    if query["status"] is not None:
        rows = [r for r in rows if r["status"] == query["status"]]
    page = paginate(rows, query["limit"], query["offset"])
    return collection([serializers.review_submission(r) for r in page], len(rows),
                      query["limit"], query["offset"])


@bp.post("/review-submissions/<review_submission_id>/submit")
@endpoint(["Panelist"])
def submit_review(review_submission_id):
    parse_body([])
    review = must_exist("review_submissions", review_submission_id, "Review")
    enrollment = store.enrollment_of_review(review)
    require_owner(enrollment["panelist_id"])
    if review["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_REVIEW_STATE",
                       "Review status is '%s', not DRAFT" % review["status"])
    campaign = store.campaign_of_enrollment(enrollment)
    require_campaign_status(campaign, REVIEW_CAMPAIGN_STATUSES)
    require_not_banned(store.panelist_of_enrollment(enrollment))

    # rung 26 first, then the three content gates in ladder order
    if enrollment["obligation_status"] != "REVIEW_DUE":
        raise ApiError("ERR_ENROLLMENT_NOT_ELIGIBLE_FOR_REVIEW",
                       "Obligation status is '%s', not REVIEW_DUE"
                       % enrollment["obligation_status"])
    _content_gates(review, campaign)

    review["status"] = "SUBMITTED"
    if not review["first_submitted_at"]:
        review["first_submitted_at"] = clock.now_iso()
    touch(review)
    return single(serializers.review_submission(review))


@bp.post("/review-submissions/<review_submission_id>/moderate")
@endpoint(["ComplianceModerator"])
def moderate_review(review_submission_id):
    body, _ = parse_body(MODERATE_FIELDS)
    review = must_exist("review_submissions", review_submission_id, "Review")
    if review["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_REVIEW_STATE",
                       "Review status is '%s', not SUBMITTED" % review["status"])

    decision = body["decision"]
    if decision == "APPROVE":
        require_segregation(review["changes_requested_by_user_id"],
                            "The moderator who requested changes may not approve "
                            "this review")

    review["moderator_note"] = body["moderator_note"]
    enrollment = store.enrollment_of_review(review)
    campaign = store.campaign_of_enrollment(enrollment) if enrollment else None

    if decision == "APPROVE":
        review["status"] = "APPROVED"
        review["approved_by_user_id"] = acting_user_id()
        touch(review)
        if campaign is not None:
            campaign["approved_review_count"] += 1
            touch(campaign)
        if enrollment is not None and enrollment["obligation_status"] == "REVIEW_DUE":
            enrollment["obligation_status"] = "REVIEW_FULFILLED"
            touch(enrollment)
    elif decision == "REQUEST_CHANGES":
        review["status"] = "CHANGES_REQUESTED"
        review["changes_requested_by_user_id"] = acting_user_id()
        touch(review)
    else:
        review["status"] = "DISCLOSURE_REJECTED"
        touch(review)
        if campaign is not None:
            campaign["disclosure_rejected_review_count"] += 1
            calc.refresh_posture(campaign)
            touch(campaign)

    return single(serializers.review_submission(review))


@bp.post("/review-submissions/<review_submission_id>/revise")
@endpoint(["Panelist"])
def revise_review(review_submission_id):
    body, present = parse_body(REVISE_FIELDS)
    review = must_exist("review_submissions", review_submission_id, "Review")
    enrollment = store.enrollment_of_review(review)
    require_owner(enrollment["panelist_id"])
    if review["status"] != "CHANGES_REQUESTED":
        raise ApiError("ERR_INVALID_REVIEW_STATE",
                       "Review status is '%s', not CHANGES_REQUESTED" % review["status"])
    require_not_banned(store.panelist_of_enrollment(enrollment))
    campaign = store.campaign_of_enrollment(enrollment)

    candidate = dict(review)
    candidate["headline"] = body["headline"]
    candidate["body_text"] = body["body_text"]
    candidate["star_rating"] = body["star_rating"]
    candidate["word_count"] = calc.word_count(body["body_text"])
    if "disclosure_statement" in present:
        candidate["disclosure_statement"] = body["disclosure_statement"]
    if "honest_opinion_attested" in present:
        candidate["honest_opinion_attested"] = bool(body["honest_opinion_attested"])

    _content_gates(candidate, campaign)

    review["headline"] = candidate["headline"]
    review["body_text"] = candidate["body_text"]
    review["star_rating"] = candidate["star_rating"]
    review["word_count"] = candidate["word_count"]
    review["disclosure_statement"] = candidate["disclosure_statement"]
    review["honest_opinion_attested"] = candidate["honest_opinion_attested"]
    review["revision_count"] += 1
    review["status"] = "SUBMITTED"
    touch(review)
    return single(serializers.review_submission(review))
