"""CompanyMetric routes (PRD 3.1 / 3.4)."""

from decimal import Decimal

from flask import Blueprint

import db
from errors import ApiError
from middleware import (COMPENSATION_COMMITTEE, FINANCE_CONTROLLER, PLAN_ADMIN,
                        authenticate, get_body, opt_string, query_param,
                        req_id, req_number, req_percent, req_string)
from response import object_response
from routes.common import paginated
from serialize import metric_out
from services import calc, lookup

bp = Blueprint("company_metrics", __name__)

READ_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, FINANCE_CONTROLLER]
SETUP_STATUSES = ("DRAFT", "TARGETS_SET")


@bp.route("/company-metrics", methods=["POST"])
def create_company_metric():
    authenticate([PLAN_ADMIN])
    body = get_body()

    plan_id = req_id(body, "plan_id")
    metric_code = req_string(body, "metric_code")
    weight = req_percent(body, "weight_pct", minimum="0.01", maximum=100)
    threshold = req_number(body, "threshold_value")
    target = req_number(body, "target_value")
    maximum = req_number(body, "max_value")

    plan = lookup.plan(plan_id)

    if not (threshold < target < maximum):
        raise ApiError("ERR_METRIC_BAND_INVALID")
    for existing in db.plan_metrics(plan_id):
        if existing["metric_code"] == metric_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "Metric code '%s' already exists in this plan" % metric_code)
    if plan["status"] not in SETUP_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_SETUP")

    metric = db.base_record()
    metric.update({
        "plan_id": plan_id,
        "metric_code": metric_code,
        "weight_pct": weight,
        "threshold_value": threshold,
        "target_value": target,
        "max_value": maximum,
        "actual_value": None,
        "source_note": None,
        "achievement_pct": Decimal("0.00"),
        "status": "DRAFT",
    })
    db.company_metrics[metric["id"]] = metric
    return object_response(metric_out(metric), 201)


@bp.route("/company-metrics/<metric_id>/actual", methods=["POST"])
def file_actual(metric_id):
    authenticate([PLAN_ADMIN])
    metric = lookup.metric(metric_id)
    body = get_body()
    actual = req_number(body, "actual_value")
    source_note = opt_string(body, "source_note")

    plan = lookup.plan(metric["plan_id"])
    if plan["status"] not in SETUP_STATUSES:
        raise ApiError("ERR_PLAN_NOT_IN_SETUP")
    if metric["status"] != "DRAFT":
        raise ApiError("ERR_METRIC_ACTUAL_ALREADY_FILED")

    metric["actual_value"] = actual
    if source_note is not None:
        metric["source_note"] = source_note
    metric["achievement_pct"] = calc.metric_achievement(
        actual, metric["threshold_value"], metric["target_value"],
        metric["max_value"])
    metric["status"] = "ACTUAL_ENTERED"
    db.touch(metric)
    return object_response(metric_out(metric))


@bp.route("/company-metrics/<metric_id>", methods=["GET"])
def get_company_metric(metric_id):
    authenticate(READ_ROLES)
    return object_response(metric_out(lookup.metric(metric_id)))


@bp.route("/company-metrics", methods=["GET"])
def list_company_metrics():
    authenticate(READ_ROLES)
    plan_id = query_param("plan_id")
    status = query_param("status")
    records = db.ordered(db.company_metrics)
    if plan_id is not None:
        records = [r for r in records if r["plan_id"] == plan_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginated(records, metric_out)
