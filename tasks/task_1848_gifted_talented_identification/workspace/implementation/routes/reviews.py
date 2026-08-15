"""CommitteeReview top-level endpoints: get, votes, conclude."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_COMMITTEE_CONFLICT_OF_INTEREST,
    ERR_DUPLICATE_VOTE,
    ERR_INVALID_REVIEW_STATE,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    get_json_body,
    require_fields,
    require_enum,
    get_or_404,
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_created,
    serialize_review,
    serialize_vote,
)
from services import domain

bp = Blueprint("reviews", __name__)


@bp.route("/gifted/committee-reviews/<rid>", methods=["GET"])
def get_review(rid):
    require_roles(*ALL_ROLES)
    review = get_or_404(db.committee_reviews, rid, "committee review")
    return success_object(serialize_review(review), 200)


@bp.route("/gifted/committee-reviews/<rid>/votes", methods=["POST"])
def cast_vote(rid):
    user_id, role = require_roles("CommitteeMember")
    review = get_or_404(db.committee_reviews, rid, "committee review")
    body = get_json_body()
    require_fields(body, ["verdict"])
    verdict = require_enum(body, "verdict", {"QUALIFY", "DENY", "ABSTAIN"})

    # state gate (priority 7)
    if review["status"] != "VOTING":
        raise ApiError(ERR_INVALID_REVIEW_STATE, "votes may be cast only while the review is VOTING", 409)

    # conflict of interest (priority 8)
    case = db.gifted_cases.get(review["case_id"])
    if case is not None and case.get("referrer_user_id") and user_id == case["referrer_user_id"]:
        raise ApiError(ERR_COMMITTEE_CONFLICT_OF_INTEREST, "voter must not equal the case's referrer_user_id", 403)

    # one vote per member per review (priority 10)
    for v in db.committee_votes.values():
        if v["review_id"] == rid and v["member_user_id"] == user_id:
            raise ApiError(ERR_DUPLICATE_VOTE, "member already cast a vote on this review", 409)

    ts = now_iso()
    vote = {
        "id": new_id(),
        "review_id": rid,
        "member_user_id": user_id,
        "verdict": verdict,
        "created_at": ts,
    }
    db.committee_votes[vote["id"]] = vote

    # auto-decide on threshold lock
    q = d = a = 0
    for v in db.committee_votes.values():
        if v["review_id"] == rid:
            if v["verdict"] == "QUALIFY":
                q += 1
            elif v["verdict"] == "DENY":
                d += 1
            else:
                a += 1
    outcome = domain.quorum_outcome(q, d, a)
    if outcome is not None:
        domain.apply_review_decision(review, outcome)

    return success_object(serialize_vote(vote), 201)


@bp.route("/gifted/committee-reviews/<rid>/votes", methods=["GET"])
def list_votes(rid):
    require_roles(*ALL_ROLES)
    get_or_404(db.committee_reviews, rid, "committee review")
    items = [v for v in db.committee_votes.values() if v["review_id"] == rid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_vote(v) for v in page], total, limit, offset)


@bp.route("/gifted/committee-reviews/<rid>/conclude", methods=["POST"])
def conclude_review(rid):
    require_roles("GiftedCoordinator")
    review = get_or_404(db.committee_reviews, rid, "committee review")

    if review["status"] != "VOTING":
        raise ApiError(ERR_INVALID_REVIEW_STATE, "conclude requires review status VOTING", 409)

    q = d = a = 0
    for v in db.committee_votes.values():
        if v["review_id"] == rid:
            if v["verdict"] == "QUALIFY":
                q += 1
            elif v["verdict"] == "DENY":
                d += 1
            else:
                a += 1
    outcome = domain.force_conclude_outcome(q, d, a)
    domain.apply_review_decision(review, outcome)
    return success_object(serialize_review(review), 200)
