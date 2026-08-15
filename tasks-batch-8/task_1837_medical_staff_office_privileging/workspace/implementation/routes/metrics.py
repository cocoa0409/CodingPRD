from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import (get_body, is_num, paginate, parse_dt, parse_dt_field,
                  require_enum, require_fields)

bp = Blueprint("metrics", __name__)

COORD = "MedicalStaffCoordinator"

DOMAINS = ("CLINICAL_QUALITY", "PATIENT_SAFETY", "DOCUMENTATION",
           "CITIZENSHIP", "UTILIZATION")


def _get_metric(mid):
    rec = db.metrics.get(mid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "PerformanceMetric not found")
    return rec


@bp.route("/mso/performance-metrics", methods=["POST"])
@require_roles(COORD)
def create_metric():
    body = get_body()
    # Rung 3: existence.
    review_id = body.get("review_id")
    review = None
    if review_id is not None:
        review = db.reviews.get(review_id)
        if review is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "PerformanceReview not found")
    # Rung 5: state — metrics attach during collection / evaluation; while a
    # grant is suspended its reviews stay open but metric recording is
    # blocked.
    if review is not None:
        if review["review_status"] not in ("COLLECTING", "EVALUATION"):
            errors.raise_err(errors.ERR_INVALID_STATE,
                             "Review is not open for metric collection")
        grant = db.grants.get(review["privilege_grant_id"])
        if grant is not None and grant["grant_status"] == "SUSPENDED":
            errors.raise_err(errors.ERR_INVALID_STATE,
                             "The grant under review is suspended; metric "
                             "recording is blocked")
    # Rung 8: temporal — collected_at inside [period_start, period_end).
    collected_raw = body.get("collected_at")
    if review is not None and collected_raw is not None:
        collected = parse_dt_field(collected_raw, "collected_at")
        if not (parse_dt(review["period_start"]) <= collected
                < parse_dt(review["period_end"])):
            errors.raise_err(errors.ERR_METRIC_OUTSIDE_WINDOW,
                             "collected_at must fall inside the review window "
                             "[period_start, period_end)")
    # Rung 9: same-domain metrics carry equal domain_weight.
    domain = body.get("metric_domain")
    weight = body.get("domain_weight")
    if review is not None and domain is not None and is_num(weight):
        for m in services.review_metrics(review["id"]):
            if (m["metric_status"] == "ACTIVE"
                    and m["metric_domain"] == domain
                    and m["domain_weight"] != weight):
                errors.raise_err(
                    errors.ERR_METRIC_WEIGHT_DOMAIN_MISMATCH,
                    "Metrics sharing a domain must carry the same "
                    "domain_weight")
    # Rung 11: input shape.
    require_fields(body, ["review_id", "metric_domain", "raw_value",
                          "domain_weight", "collected_at"])
    require_enum(body, "metric_domain", DOMAINS)
    if not is_num(body["raw_value"]):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "raw_value must be numeric")
    if not is_num(body["domain_weight"]):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "domain_weight must be numeric")
    passed = body.get("passed_fppe_case", False)
    if not isinstance(passed, bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST,
                         "passed_fppe_case must be a boolean")

    rec = services.base_record()
    rec.update({
        "review_id": review_id,
        "metric_domain": domain,
        "raw_value": body["raw_value"],
        "normalized_value": services.normalize_metric(body["raw_value"],
                                                      domain),
        "domain_weight": body["domain_weight"],
        "collected_at": collected_raw,
        "metric_status": "ACTIVE",
        "passed_fppe_case": passed,
    })
    db.metrics[rec["id"]] = rec
    services.recompute_review_counts(review)
    return ok_object(serializers.metric(rec), 201)


@bp.route("/mso/performance-metrics", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_metrics():
    items, limit, offset, total = paginate(
        db.metrics.values(), serializers.metric,
        ["review_id", "metric_status"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/performance-metrics/<mid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_metric(mid):
    return ok_object(serializers.metric(_get_metric(mid)))


@bp.route("/mso/performance-metrics/<mid>/retract", methods=["POST"])
@require_roles(COORD)
def retract_metric(mid):
    get_body()
    metric = _get_metric(mid)
    if metric["metric_status"] != "ACTIVE":
        errors.raise_err(errors.ERR_INVALID_STATE,
                         "Metric is not ACTIVE")
    metric["metric_status"] = "RETRACTED"
    services.touch(metric)
    review = db.reviews.get(metric["review_id"])
    if review is not None:
        services.recompute_review_counts(review)
    return ok_object(serializers.metric(metric))
