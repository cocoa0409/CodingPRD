"""Incentive metrics: goal curves, adjustments, results, certification (PRD §3.4)."""

from flask import Blueprint, request

import calc
from db import apply_changes, insert, store, touch
from errors import ApiError
from middleware import ROLE_CHAIR, ROLE_COMP_CONSULTANT, ROLE_COUNSEL, authenticate
from response import object_response
from routes.common import fetch, paginated
from services import domain
from validation import Body

bp = Blueprint("metrics", __name__)

METRIC_CODES = {"ADJ_EPS", "REVENUE_GROWTH", "FCF", "ROIC", "RTSR", "COST_RATIO"}
VEHICLES = {"ANNUAL_INCENTIVE", "LONG_TERM_PSU"}
DIRECTIONS = {"HIGHER_IS_BETTER", "LOWER_IS_BETTER"}
INTERPOLATIONS = {"LINEAR", "STEP"}


@bp.post("/exec-comp/pay-programs/<pid>/incentive-metrics")
def define_metric(pid):
    authenticate([ROLE_COMP_CONSULTANT])
    program = fetch("pay_programs", pid)
    body = Body()
    metric_code = body.enum("metric_code", METRIC_CODES, required=True)
    vehicle = body.enum("vehicle", VEHICLES, required=True)
    direction = body.enum("direction", DIRECTIONS, required=True)
    weight_pct = body.number(
        "weight_pct", required=True, minimum=5, maximum=100, places=2
    )
    threshold_value = body.number("threshold_value", required=True)
    target_value = body.number("target_value", required=True)
    maximum_value = body.number("maximum_value", required=True)
    threshold_payout_pct = body.number(
        "threshold_payout_pct", default=calc.money("50.00"), minimum=0, places=2
    )
    target_payout_pct = body.number(
        "target_payout_pct", default=calc.money("100.00"), minimum=0, places=2
    )
    maximum_payout_pct = body.number(
        "maximum_payout_pct", default=calc.money("200.00"), minimum=0, places=2
    )
    interpolation = body.enum("interpolation", INTERPOLATIONS, default="LINEAR")
    if target_value == 0:
        raise ApiError("ERR_INVALID_REQUEST", "target_value may not be zero")

    if program["design_status"] != "DRAFT":
        raise ApiError("ERR_PROGRAM_NOT_MUTABLE")
    for existing in domain.program_metrics(program["id"]):
        if existing["metric_code"] == metric_code and existing["vehicle"] == vehicle:
            raise ApiError("ERR_METRIC_ALREADY_DEFINED")
    if not calc.curve_is_monotonic(direction, threshold_value, target_value, maximum_value):
        raise ApiError("ERR_GOAL_CURVE_NOT_MONOTONIC")

    metric = insert(
        store.incentive_metrics,
        {
            "pay_program_id": program["id"],
            "metric_code": metric_code,
            "vehicle": vehicle,
            "direction": direction,
            "weight_pct": weight_pct,
            "threshold_value": threshold_value,
            "target_value": target_value,
            "maximum_value": maximum_value,
            "threshold_payout_pct": threshold_payout_pct,
            "target_payout_pct": target_payout_pct,
            "maximum_payout_pct": maximum_payout_pct,
            "interpolation": interpolation,
            "locked_target_value": None,
            "goal_adjustment_pct": None,
            "as_reported_value": None,
            "non_gaap_adjusted_value": None,
            "result_adjustment_reason": None,
            "achieved_value": None,
            "payout_factor_pct": None,
            "original_payout_factor_pct": None,
            "restated_payout_factor_pct": None,
            "status": "DRAFT",
            "adjusted_by_user_id": None,
            "certified_by_user_id": None,
        },
    )
    return object_response(metric, 201)


@bp.get("/exec-comp/pay-programs/<pid>/incentive-metrics")
def list_metrics(pid):
    authenticate([ROLE_COMP_CONSULTANT, ROLE_CHAIR, ROLE_COUNSEL])
    program = fetch("pay_programs", pid)
    rows = domain.program_metrics(program["id"])
    vehicle = request.args.get("vehicle")
    if vehicle is not None:
        rows = [r for r in rows if r["vehicle"] == vehicle]
    return paginated(rows)


@bp.post("/exec-comp/incentive-metrics/<mid>/adjustments")
def adjust_metric(mid):
    user_id, _ = authenticate([ROLE_CHAIR])
    metric = fetch("incentive_metrics", mid)
    body = Body()
    new_target = body.number("target_value")
    new_threshold = body.number("threshold_value")
    new_maximum = body.number("maximum_value")
    reason = body.string("result_adjustment_reason", required=True, max_len=2000)
    expected_version = body.integer("expected_incentive_metric_version", required=True)

    if expected_version != metric["version"]:
        raise ApiError("ERR_STALE_INCENTIVE_METRIC_VERSION")
    if metric["status"] != "LOCKED":
        raise ApiError("ERR_METRIC_STATE_INVALID")

    target = metric["target_value"] if new_target is None else new_target
    threshold = metric["threshold_value"] if new_threshold is None else new_threshold
    maximum = metric["maximum_value"] if new_maximum is None else new_maximum
    if not calc.curve_is_monotonic(metric["direction"], threshold, target, maximum):
        raise ApiError("ERR_GOAL_CURVE_NOT_MONOTONIC")

    magnitude = calc.goal_adjustment_pct(target, metric["locked_target_value"])
    if magnitude > calc.ADJUSTMENT_LIMIT_PCT:
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_POLICY_LIMIT")

    apply_changes(
        metric,
        {
            "target_value": target,
            "threshold_value": threshold,
            "maximum_value": maximum,
            "goal_adjustment_pct": magnitude,
            "result_adjustment_reason": reason,
            "status": "ADJUSTED",
            "adjusted_by_user_id": user_id,
        },
    )
    touch(metric)
    program = store.pay_programs[metric["pay_program_id"]]
    domain.mark_screens_stale(program)
    return object_response(metric)


@bp.post("/exec-comp/incentive-metrics/<mid>/results")
def submit_result(mid):
    authenticate([ROLE_COMP_CONSULTANT])
    metric = fetch("incentive_metrics", mid)
    body = Body()
    as_reported = body.number("as_reported_value", required=True)
    non_gaap = body.number("non_gaap_adjusted_value")
    reason_supplied = body.present("result_adjustment_reason")
    reason = body.string("result_adjustment_reason", max_len=2000)

    if metric["status"] not in ("LOCKED", "ADJUSTED"):
        raise ApiError("ERR_METRIC_STATE_INVALID")

    changes = {
        "as_reported_value": as_reported,
        "non_gaap_adjusted_value": non_gaap,
        "achieved_value": as_reported if non_gaap is None else non_gaap,
        "status": "RESULT_SUBMITTED",
    }
    if reason_supplied:
        changes["result_adjustment_reason"] = reason
    apply_changes(metric, changes)
    touch(metric)
    return object_response(metric)


@bp.post("/exec-comp/incentive-metrics/<mid>/certify-result")
def certify_result(mid):
    user_id, _ = authenticate([ROLE_CHAIR])
    metric = fetch("incentive_metrics", mid)
    if metric["adjusted_by_user_id"] is not None and (
        user_id == metric["adjusted_by_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if metric["status"] != "RESULT_SUBMITTED":
        raise ApiError("ERR_METRIC_STATE_INVALID")

    factor = calc.metric_payout_factor(metric, metric["achieved_value"])
    changes = {
        "payout_factor_pct": factor,
        "status": "CERTIFIED",
        "certified_by_user_id": user_id,
    }
    if metric["original_payout_factor_pct"] is None:
        changes["original_payout_factor_pct"] = factor
    apply_changes(metric, changes)
    touch(metric)

    program = store.pay_programs[metric["pay_program_id"]]
    vehicle_metrics = domain.program_metrics(program["id"], metric["vehicle"])
    if calc.certified_vehicle_factor(vehicle_metrics) is not None:
        domain.recompute_vehicle_awards(program, metric["vehicle"])
        before = domain.watched(program)
        domain.recompute_program_alignment(program)
        domain.stale_if_watched_changed(program, before)
    return object_response(metric)
