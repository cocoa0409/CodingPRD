"""Quality reviews: open, complete (with rebuke cascade), list, get."""

from flask import Blueprint, request

import db
import services
import util
from errors import (
    ApiError,
    ERR_NOT_REVIEW_OWNER,
    ERR_RESPONSE_NOT_SUBMITTED,
    ERR_REVIEWER_IS_RESPONDER,
    ERR_REVIEW_NOT_PENDING,
    ERR_VERDICT_SCORE_MISMATCH,
)
from middleware import require_roles, ANY_ROLE
from response import ok, ok_list
from util import serialize, serialize_list

bp = Blueprint("reviews", __name__)


@bp.route("/econsult/quality-reviews", methods=["POST"])
def create_review():
    uid, _role = require_roles("QualityReviewer")
    data = util.json_body()
    response_id = util.req_str(data, "response_id")

    resp = services.get_response(response_id)
    if resp["status"] != "SUBMITTED":
        raise ApiError(
            ERR_RESPONSE_NOT_SUBMITTED, 409,
            "A quality review can only be opened on a SUBMITTED response",
        )
    if uid == resp["specialist_id"]:
        raise ApiError(
            ERR_REVIEWER_IS_RESPONDER, 403,
            "The quality reviewer must differ from the responding specialist",
        )

    rec = services.base_record()
    rec.update({
        "response_id": resp["id"],
        "reviewer_specialist_id": uid,
        "timeliness_score": None,
        "appropriateness_score": None,
        "clarity_score": None,
        "composite_score_bps": None,
        "verdict": None,
        "status": "PENDING",
    })
    db.store["quality_reviews"][rec["id"]] = rec
    return ok(serialize("quality_review", rec), 201)


@bp.route("/econsult/quality-reviews/<rid>/complete", methods=["POST"])
def complete_review(rid):
    uid, _role = require_roles("QualityReviewer")
    data = util.json_body()
    timeliness = util.req_int(data, "timeliness_score", min_v=1, max_v=5)
    appropriateness = util.req_int(data, "appropriateness_score", min_v=1, max_v=5)
    clarity = util.req_int(data, "clarity_score", min_v=1, max_v=5)
    verdict = util.req_enum(data, "verdict", util.VERDICTS)

    review = services.get_review(rid)
    if review["reviewer_specialist_id"] != uid:
        raise ApiError(ERR_NOT_REVIEW_OWNER, 403, "Caller is not the review's reviewer")
    if review["status"] != "PENDING":
        raise ApiError(ERR_REVIEW_NOT_PENDING, 409, "Review is not PENDING")

    composite = services.rhu(
        appropriateness * 50 + timeliness * 25 + clarity * 25, 5
    ) * 100
    band = "PASS" if composite >= 6000 else "REBUKE"
    if verdict != band:
        raise ApiError(
            ERR_VERDICT_SCORE_MISMATCH, 422,
            "Verdict contradicts the computed composite band",
        )

    review["timeliness_score"] = timeliness
    review["appropriateness_score"] = appropriateness
    review["clarity_score"] = clarity
    review["composite_score_bps"] = composite
    review["verdict"] = verdict
    review["status"] = "COMPLETED"
    services.touch(review)

    resp = db.store["consult_responses"][review["response_id"]]
    membership = db.store["panel_memberships"][resp["_membership_id"]]
    membership["reviews_count"] += 1
    membership["reviews_score_sum"] += composite

    if verdict == "REBUKE":
        if resp["status"] == "SUBMITTED":
            resp["status"] = "REBUKED"
            services.touch(resp)
        services.reverse_provisional_entries(resp["consult_id"])
        membership["rebuke_count"] += 1

    services.recompute_quality(membership)
    return ok(serialize("quality_review", review), 200)


@bp.route("/econsult/quality-reviews", methods=["GET"])
def list_reviews():
    require_roles(*ANY_ROLE)
    response_id = request.args.get("response_id")
    reviewer_id = request.args.get("reviewer_specialist_id")
    records = list(db.store["quality_reviews"].values())
    if response_id is not None:
        records = [r for r in records if r["response_id"] == response_id]
    if reviewer_id is not None:
        records = [r for r in records if r["reviewer_specialist_id"] == reviewer_id]
    page, total, limit, offset = util.paginate(records)
    return ok_list(serialize_list("quality_review", page), total, limit, offset)


@bp.route("/econsult/quality-reviews/<rid>", methods=["GET"])
def get_review(rid):
    require_roles(*ANY_ROLE)
    return ok(serialize("quality_review", services.get_review(rid)), 200)
