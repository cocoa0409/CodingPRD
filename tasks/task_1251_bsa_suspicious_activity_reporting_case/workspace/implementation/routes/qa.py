"""QA sampling reviews (monthly quota) — distinct from case/SAR QA gates."""
from flask import Blueprint, request

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body, pagination_params
from services.core import qa_quota
from util import QA_OUTCOMES, base_entity, opt_str, req_enum, req_int, serialize, sort_created, touch

bp = Blueprint("qa", __name__)


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


@bp.route("/qa-reviews", methods=["POST"])
def create_qa_review():
    body = get_body()
    case_id = body.get("case_id")
    sar_id = body.get("sar_report_id")
    if case_id is not None and not isinstance(case_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'case_id' must be a string", 400)
    if sar_id is not None and not isinstance(sar_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'sar_report_id' must be a string", 400)
    if (case_id is None) == (sar_id is None):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Exactly one of case_id / sar_report_id must be set", 400)
    user_id, role = authn()
    authz(role, ["QAReviewer"])
    if case_id is not None:
        _get(db.cases, case_id, "Case")
    else:
        _get(db.sars, sar_id, "SARReport")
    duplicate = any(
        q["status"] == "SAMPLED"
        and ((case_id is not None and q["case_id"] == case_id)
             or (sar_id is not None and q["sar_report_id"] == sar_id))
        for q in db.qa_reviews.values())
    if duplicate:
        raise ApiError("ERR_INVALID_REQUEST",
                       "An active QAReview sample already exists for this target", 400)
    quota, sampled = qa_quota()
    if sampled >= quota:
        raise ApiError("ERR_QA_QUOTA_EXCEEDED",
                       "Monthly QA sample quota already reached", 422)
    review = base_entity()
    review.update({
        "case_id": case_id,
        "sar_report_id": sar_id,
        "period_month": db.now().strftime("%Y-%m"),
        "reviewer_id": user_id,
        "outcome": "PENDING",
        "defect_count": None,
        "notes": None,
        "status": "SAMPLED",
    })
    db.qa_reviews[review["id"]] = review
    return response.success(serialize(review), status=201)


@bp.route("/qa-reviews", methods=["GET"])
def list_qa_reviews():
    _, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(db.qa_reviews.values())
    for field in ("case_id", "sar_report_id"):
        value = request.args.get(field)
        if value is not None:
            items = [q for q in items if q.get(field) == value]
    items = sort_created(items)
    return response.paginated([serialize(q) for q in items], limit, offset)


@bp.route("/qa-reviews/<rid>", methods=["GET"])
def get_qa_review(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    review = _get(db.qa_reviews, rid, "QAReview")
    return response.success(serialize(review), status=200)


@bp.route("/qa-reviews/<rid>/complete", methods=["POST"])
def complete_qa_review(rid):
    body = get_body()
    outcome = req_enum(body, "outcome", QA_OUTCOMES)
    defect_count = req_int(body, "defect_count", minimum=0)
    notes = opt_str(body, "notes")
    user_id, role = authn()
    authz(role, ["QAReviewer"])
    review = _get(db.qa_reviews, rid, "QAReview")
    if review["reviewer_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the named reviewer may complete the sample", 403)
    if review["status"] != "SAMPLED":
        raise ApiError("ERR_INVALID_STATE",
                       f"QAReview in status {review['status']} cannot be completed", 409)
    review["outcome"] = outcome
    review["defect_count"] = defect_count
    if notes is not None:
        review["notes"] = notes
    review["status"] = "COMPLETED"
    touch(review)
    return response.success(serialize(review), status=200)
