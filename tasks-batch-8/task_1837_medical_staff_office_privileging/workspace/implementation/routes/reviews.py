from decimal import Decimal

from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import (check_dt_order, get_body, is_num, paginate, parse_dt_field,
                  require_enum, require_fields)

bp = Blueprint("reviews", __name__)

COORD = "MedicalStaffCoordinator"
CHAIR = "CredentialsCommitteeChair"

REVIEW_KINDS = ("FPPE", "OPPE")


def _get_review(rid):
    rec = db.reviews.get(rid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "PerformanceReview not found")
    return rec


@bp.route("/mso/performance-reviews", methods=["POST"])
@require_roles(COORD)
def create_review():
    body = get_body()
    # Rung 3: existence.
    member_id = body.get("member_id")
    if member_id is not None and member_id not in db.members:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    grant_id = body.get("privilege_grant_id")
    if grant_id is not None and grant_id not in db.grants:
        errors.raise_err(errors.ERR_NOT_FOUND, "PrivilegeGrant not found")
    # Rung 11: input shape.
    require_fields(body, ["member_id", "privilege_grant_id", "review_kind",
                          "period_start", "period_end"])
    require_enum(body, "review_kind", REVIEW_KINDS)
    check_dt_order(body["period_start"], body["period_end"],
                   "period_start", "period_end")
    rec = services.base_record()
    rec.update({
        "member_id": member_id,
        "privilege_grant_id": grant_id,
        "review_kind": body["review_kind"],
        "review_status": "COLLECTING",
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "provisional_composite_score": None,
        "final_composite_score": None,
        "metric_count": 0,
        "retracted_metric_count": 0,
        "outcome": None,
    })
    db.reviews[rec["id"]] = rec
    return ok_object(serializers.review(rec), 201)


@bp.route("/mso/performance-reviews", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_reviews():
    items, limit, offset, total = paginate(
        db.reviews.values(), serializers.review,
        ["member_id", "privilege_grant_id", "review_status", "review_kind"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/performance-reviews/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_review(rid):
    return ok_object(serializers.review(_get_review(rid)))


@bp.route("/mso/performance-reviews/<rid>/close-collection", methods=["POST"])
@require_roles(COORD)
def close_collection(rid):
    get_body()
    review = _get_review(rid)
    if review["review_status"] != "COLLECTING":
        errors.raise_err(errors.ERR_REVIEW_NOT_COLLECTING,
                         "Review is not in COLLECTING")
    if review["metric_count"] <= 0:
        errors.raise_err(errors.ERR_NO_METRICS,
                         "Review holds no ACTIVE metrics")
    review["review_status"] = "EVALUATION"
    services.touch(review)
    return ok_object(serializers.review(review))


@bp.route("/mso/performance-reviews/<rid>/compute-provisional", methods=["POST"])
@require_roles(COORD)
def compute_provisional(rid):
    get_body()
    review = _get_review(rid)
    if review["review_status"] != "EVALUATION":
        errors.raise_err(errors.ERR_REVIEW_NOT_EVALUABLE,
                         "Review is not in EVALUATION")
    review["provisional_composite_score"] = services.composite_score(
        review, "provisional")
    review["review_status"] = "PROVISIONAL_RESULT"
    services.touch(review)
    return ok_object(serializers.review(review))


@bp.route("/mso/performance-reviews/<rid>/finalize", methods=["POST"])
@require_roles(CHAIR)
def finalize_review(rid):
    get_body()
    review = _get_review(rid)
    if review["review_status"] != "PROVISIONAL_RESULT":
        errors.raise_err(errors.ERR_REVIEW_NOT_PROVISIONAL,
                         "Review is not in PROVISIONAL_RESULT")
    active = [m for m in services.review_metrics(rid)
              if m["metric_status"] == "ACTIVE"]
    weight_sum = sum(Decimal(str(m["domain_weight"])) for m in active)
    if weight_sum != Decimal("1.000"):
        errors.raise_err(errors.ERR_WEIGHT_SUM_INVALID,
                         "ACTIVE metric weights must sum to exactly 1.000")
    review["final_composite_score"] = services.composite_score(review, "final")
    review["outcome"] = services.outcome_for(review["final_composite_score"])
    review["review_status"] = "FINAL_RESULT"
    services.touch(review)

    # Cascade link 1: OPPE UNSATISFACTORY auto-proposes a RESTRICTION case.
    if review["review_kind"] == "OPPE" and review["outcome"] == "UNSATISFACTORY":
        services.create_case(
            subject_member_id=review["member_id"],
            proposed_by_member_id=None,
            case_kind="RESTRICTION",
            restriction_days=0,
            linked_review_id=review["id"],
        )

    # FPPE propagation: passed cases advance the grant toward maturation.
    if review["review_kind"] == "FPPE" and review["outcome"] in (
            "SATISFACTORY", "MARGINAL"):
        grant = db.grants.get(review["privilege_grant_id"])
        if grant is not None:
            from util import parse_dt
            period_end = parse_dt(review["period_end"])
            passed = sum(
                1 for m in active
                if m.get("passed_fppe_case")
                and parse_dt(m["collected_at"]) < period_end)
            if passed:
                grant["fppe_cases_completed"] = \
                    grant.get("fppe_cases_completed", 0) + passed
                services.touch(grant)
            services.maybe_activate_grant(grant)
    return ok_object(serializers.review(review))


@bp.route("/mso/performance-reviews/<rid>/close", methods=["POST"])
@require_roles(CHAIR)
def close_review(rid):
    get_body()
    review = _get_review(rid)
    if review["review_status"] != "FINAL_RESULT":
        errors.raise_err(errors.ERR_INVALID_STATE,
                         "Review is not in FINAL_RESULT")
    review["review_status"] = "CLOSED"
    services.touch(review)
    return ok_object(serializers.review(review))
