"""Title review and title exception routes (PRD §3.6)."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import (body, opt_enum, opt_int, opt_str, ref_not_found,
                           req_dt, req_enum, req_str)
from services import domain

bp = Blueprint("title", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
              "PlatformAdmin")
SURVEY_TYPES = {"ALTA", "BOUNDARY", "TOPOGRAPHIC"}
SEVERITIES = {"STANDARD", "MATERIAL", "FATAL"}


# ---------------------------------------------------------------------------
# TitleReview
# ---------------------------------------------------------------------------
@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews", methods=["POST"])
def create_title_review(deal_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    data = body()
    review = db.make_record({
        "deal_id": deal["id"],
        "title_company": req_str(data, "title_company"),
        "survey_type": opt_enum(data, "survey_type", SURVEY_TYPES, "ALTA"),
        "received_at": req_dt(data, "received_at"),
        "exception_count": 0,
        "status": "RECEIVED",
    })
    db.stores["title_reviews"][review["id"]] = review
    return created(db.pub(review))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews", methods=["GET"])
def list_title_reviews(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.title_reviews_of(deal["id"])
    v = request.args.get("status")
    if v is not None:
        items = [r for r in items if r["status"] == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>", methods=["GET"])
def get_title_review(deal_id, review_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_title_review_scoped(deal, review_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/begin-review", methods=["POST"])
def begin_review(deal_id, review_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    if review["status"] != "RECEIVED":
        raise ApiError("ERR_TITLE_REVIEW_INVALID_STATE",
                       "begin-review requires status RECEIVED", 409)
    review["status"] = "UNDER_REVIEW"
    bump(review)
    return ok(db.pub(review))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/clear", methods=["POST"])
def clear_review(deal_id, review_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    if review["status"] not in ("UNDER_REVIEW", "EXCEPTIONS_RAISED"):
        raise ApiError("ERR_TITLE_REVIEW_INVALID_STATE",
                       "clear requires status UNDER_REVIEW or EXCEPTIONS_RAISED", 409)
    if review["exception_count"] != 0:
        raise ApiError("ERR_UNRESOLVED_TITLE_EXCEPTIONS",
                       "clear requires exception_count == 0", 422)
    review["status"] = "CLEARED"
    bump(review)
    # A cleared title review satisfies both milestones in one stroke.
    domain.satisfy_milestone(deal, "TITLE_REVIEW")
    domain.satisfy_milestone(deal, "SURVEY_REVIEW")
    domain.recompute_posture(deal)
    return ok(db.pub(review))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/reject", methods=["POST"])
def reject_review(deal_id, review_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    if review["status"] not in ("UNDER_REVIEW", "EXCEPTIONS_RAISED"):
        raise ApiError("ERR_TITLE_REVIEW_INVALID_STATE",
                       "reject requires status UNDER_REVIEW or EXCEPTIONS_RAISED", 409)
    has_fatal = any(ex["severity"] == "FATAL" and ex["status"] in ("OPEN", "CURE_PROPOSED")
                    for ex in domain.exceptions_of(review["id"]))
    if not has_fatal:
        raise ApiError("ERR_NO_FATAL_EXCEPTION",
                       "reject requires at least one FATAL exception", 422)
    review["status"] = "REJECTED"
    bump(review)
    domain.recompute_posture(deal)  # unresolved FATAL -> DD_BLOCKED
    return ok(db.pub(review))


# ---------------------------------------------------------------------------
# TitleException
# ---------------------------------------------------------------------------
@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/exceptions", methods=["POST"])
def create_exception(deal_id, review_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    if review["status"] not in ("UNDER_REVIEW", "EXCEPTIONS_RAISED"):
        raise ApiError("ERR_TITLE_REVIEW_INVALID_STATE",
                       "Exceptions can be raised only against a review in UNDER_REVIEW", 409)
    data = body()
    exception_code = req_str(data, "exception_code")
    severity = req_enum(data, "severity", SEVERITIES)
    description = req_str(data, "description")
    cure_cost = opt_int(data, "cure_cost_cents", 0)
    cured_by = opt_str(data, "cured_by_exception_id", None)
    referenced = None
    if cured_by is not None:
        referenced = db.stores["title_exceptions"].get(cured_by)
        if referenced is None or referenced["title_review_id"] != review["id"]:
            ref_not_found("cured_by_exception_id references a non-existent exception")
    ex = db.make_record({
        "title_review_id": review["id"],
        "exception_code": exception_code,
        "severity": severity,
        "description": description,
        "cured_by_exception_id": cured_by,
        "cure_cost_cents": cure_cost,
        "status": "OPEN",
    })
    db.stores["title_exceptions"][ex["id"]] = ex
    # A revised exception supersedes the cured one it links to.
    if referenced is not None and referenced["status"] == "CURED":
        referenced["status"] = "SUPERSEDED"
        bump(referenced)
    if review["status"] == "UNDER_REVIEW":
        review["status"] = "EXCEPTIONS_RAISED"
        bump(review)
    domain.recompute_exception_count(review)
    domain.recompute_posture(deal)  # FATAL severity -> DD_BLOCKED
    return created(db.pub(ex))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/exceptions", methods=["GET"])
def list_exceptions(deal_id, review_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    items = domain.exceptions_of(review["id"])
    for param in ("status", "severity"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if str(e.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/exceptions/<ex_id>", methods=["GET"])
def get_exception(deal_id, review_id, ex_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    return ok(db.pub(domain.get_exception_scoped(review, ex_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/exceptions/<ex_id>/propose-cure", methods=["POST"])
def propose_cure(deal_id, review_id, ex_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    ex = domain.get_exception_scoped(review, ex_id)
    if ex["status"] != "OPEN":
        raise ApiError("ERR_EXCEPTION_INVALID_STATE",
                       "propose-cure requires status OPEN", 409)
    ex["status"] = "CURE_PROPOSED"
    bump(ex)
    return ok(db.pub(ex))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/exceptions/<ex_id>/confirm-cure", methods=["POST"])
def confirm_cure(deal_id, review_id, ex_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    ex = domain.get_exception_scoped(review, ex_id)
    if ex["status"] != "CURE_PROPOSED":
        raise ApiError("ERR_EXCEPTION_INVALID_STATE",
                       "confirm-cure requires status CURE_PROPOSED", 409)
    if (ex["severity"] in ("MATERIAL", "FATAL")
            and ex["cure_cost_cents"] > domain.TITLE_CURE_THRESHOLD_CENTS
            and body().get("committee_sign_off") is not True):
        raise ApiError("ERR_CURE_COST_NEEDS_COMMITTEE",
                       "MATERIAL/FATAL cure above the cost threshold requires committee sign-off", 422)
    ex["status"] = "CURED"
    bump(ex)
    domain.recompute_exception_count(review)
    # Curing the last FATAL exception may lift the deal out of DD_BLOCKED.
    domain.recompute_posture(deal)
    return ok(db.pub(ex))


@bp.route("/acquisition-deals/deals/<deal_id>/title-reviews/<review_id>/exceptions/<ex_id>/waive", methods=["POST"])
def waive_exception(deal_id, review_id, ex_id):
    require_role("UnderwritingCommittee")
    deal = domain.get_deal(deal_id)
    review = domain.get_title_review_scoped(deal, review_id)
    ex = domain.get_exception_scoped(review, ex_id)
    if ex["status"] != "OPEN":
        raise ApiError("ERR_EXCEPTION_INVALID_STATE",
                       "waive requires status OPEN", 409)
    if ex["severity"] == "FATAL":
        raise ApiError("ERR_FATAL_NOT_WAIVABLE",
                       "FATAL title exceptions cannot be waived", 422)
    ex["status"] = "WAIVED"
    bump(ex)
    domain.recompute_exception_count(review)
    domain.recompute_posture(deal)
    return ok(db.pub(ex))
