"""CommitteeReview and CommitteeVote endpoints."""

import uuid
from datetime import timedelta

from flask import Blueprint, request as freq

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_REVIEW_NOT_FOUND,
    ERR_REVIEW_NOT_MAINTAIN_DECISION,
    ERR_REVIEW_NOT_OPEN,
    ERR_STALE_VERSION,
)
from middleware import get_auth, require_roles, get_json_body
from response import success_object, paginate
from serializers import review_json, vote_json
from services import (
    COMMITTEE_QUORUM,
    apply_reduce_decision,
    recompute_review_tallies,
    touch,
)
from util import is_int, now_iso, parse_date

bp = Blueprint("reviews", __name__)

REVIEW_STATUSES = {"OPEN", "DECIDED"}
VOTE_VALUES = {"REDUCE", "MAINTAIN", "ABSTAIN"}


@bp.route("/committee-reviews", methods=["GET"])
def list_reviews():
    get_auth()
    items = list(db.reviews.values())
    sl = freq.args.get("service_line_id")
    if sl is not None:
        items = [r for r in items if r["service_line_id"] == sl]
    ur = freq.args.get("utilization_report_id")
    if ur is not None:
        items = [r for r in items if r["utilization_report_id"] == ur]
    st = freq.args.get("status")
    if st is not None:
        if st not in REVIEW_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [r for r in items if r["status"] == st]
    out = [review_json(r) for r in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/committee-reviews/<reviewId>", methods=["GET"])
def get_review(reviewId):
    get_auth()
    rec = db.reviews.get(reviewId)
    if rec is None:
        raise ApiError(ERR_REVIEW_NOT_FOUND, 404, "committee review not found")
    return success_object(review_json(rec))


@bp.route("/committee-reviews/<reviewId>/votes", methods=["POST"])
def cast_vote(reviewId):
    auth = require_roles("CommitteeMember")
    review = db.reviews.get(reviewId)
    if review is None:
        raise ApiError(ERR_REVIEW_NOT_FOUND, 404, "committee review not found")
    body = get_json_body()
    vote = body.get("vote")
    expected = body.get("expected_review_version")
    # shape
    if vote not in VOTE_VALUES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid vote value")
    if not is_int(expected):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "expected_review_version is required and must be an integer",
        )
    # state
    if review["status"] != "OPEN":
        raise ApiError(ERR_REVIEW_NOT_OPEN, 409, "vote requires review status OPEN")
    # OCC
    if expected != review["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_review_version does not match the current version",
        )
    # re-cast deletes the member's prior row
    for v in list(db.votes.values()):
        if v["review_id"] == review["id"] and v["member_ref"] == auth.user_id:
            del db.votes[v["id"]]
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_insert_seq": db.next_insert_seq(),
        "review_id": review["id"],
        "member_ref": auth.user_id,
        "vote": vote,
    }
    db.votes[row["id"]] = row
    recompute_review_tallies(review)
    touch(review)
    # quorum -> auto-decision
    total = (
        review["tally_reduce"] + review["tally_maintain"] + review["tally_abstain"]
    )
    if total >= COMMITTEE_QUORUM:
        review["decision"] = (
            "REDUCE" if review["tally_reduce"] > review["tally_maintain"] else "MAINTAIN"
        )
        review["status"] = "DECIDED"
        touch(review)  # the DECIDED transition carries its own version increment
        if review["decision"] == "REDUCE":
            apply_reduce_decision(review)
    return success_object(review_json(review), 201)


@bp.route("/committee-reviews/<reviewId>/votes", methods=["GET"])
def list_votes(reviewId):
    get_auth()
    review = db.reviews.get(reviewId)
    if review is None:
        raise ApiError(ERR_REVIEW_NOT_FOUND, 404, "committee review not found")
    items = [v for v in db.votes.values() if v["review_id"] == reviewId]
    out = [vote_json(v) for v in items]
    out.sort(key=lambda r: (r["created_at"],))
    return paginate(out)


@bp.route("/committee-reviews/<reviewId>/reopen", methods=["POST"])
def reopen_review(reviewId):
    require_roles("BlockCommitteeChair")
    review = db.reviews.get(reviewId)
    if review is None:
        raise ApiError(ERR_REVIEW_NOT_FOUND, 404, "committee review not found")
    if review["status"] != "DECIDED":
        raise ApiError(
            ERR_REVIEW_NOT_OPEN, 409, "reopen requires review status DECIDED"
        )
    if review["decision"] != "MAINTAIN":
        raise ApiError(
            ERR_REVIEW_NOT_MAINTAIN_DECISION,
            409,
            "only a MAINTAIN decision may be reopened",
        )
    # delete all vote rows, zero tallies, decision -> NONE, status -> OPEN
    for v in list(db.votes.values()):
        if v["review_id"] == review["id"]:
            del db.votes[v["id"]]
    review["tally_reduce"] = 0
    review["tally_maintain"] = 0
    review["tally_abstain"] = 0
    review["decision"] = "NONE"
    review["status"] = "OPEN"
    touch(review)
    return success_object(review_json(review))
