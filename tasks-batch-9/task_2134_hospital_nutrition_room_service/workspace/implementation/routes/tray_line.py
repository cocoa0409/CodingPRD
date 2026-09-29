"""The tray line: production, quality assurance and bedside delivery (PRD section 3.7)."""

from flask import Blueprint

import api
import calcs
import domain
import serialize
import store
from errors import ApiError

bp = Blueprint("tray_line", __name__, url_prefix="/nutrition/meal-orders")


@bp.post("/<order_id>/start-production")
@api.require("TrayAide")
def start_production(order_id):
    order = store.get_meal_order(order_id)
    period = store.meal_periods[order["meal_period_id"]]
    if order["fulfillment_status"] != "VALIDATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a VALIDATED tray may enter production.")
    if period["status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE",
                       "The meal period is not IN_SERVICE.")
    if order["revalidation_required"]:
        raise ApiError("ERR_INVALID_STATE",
                       "The tray must be validated again before entering production.")
    order["fulfillment_status"] = "IN_PRODUCTION"
    store.touch(order)
    return api.ok(serialize.meal_order(order))


@bp.post("/<order_id>/plate")
@api.require("TrayAide")
def plate(order_id):
    order = store.get_meal_order(order_id)
    if order["fulfillment_status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "Only an IN_PRODUCTION tray may be plated.")
    order["fulfillment_status"] = "PLATED"
    store.touch(order)
    return api.ok(serialize.meal_order(order))


@bp.post("/<order_id>/accuracy-check")
@api.require("TrayAide")
def accuracy_check(order_id):
    order = store.get_meal_order(order_id)
    body = api.body()
    observed = api.req_int(body, "observed_line_count", lo=0)
    defects = api.opt_str_list(body, "defect_codes", [])

    if order["fulfillment_status"] != "PLATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Quality assurance begins once the tray is PLATED.")
    if order["qa_status"] not in ("NOT_CHECKED", "ACCURACY_FAILED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The accuracy check cannot be recorded from qa_status %s."
                       % order["qa_status"])

    line_count = len(store.lines_of(order["id"]))
    passed = (observed == line_count) and not defects

    if passed:
        order["qa_status"] = "ACCURACY_PASSED"
    else:
        order["qa_status"] = "ACCURACY_FAILED"
        order["accuracy_retry_count"] += 1
    order["accuracy_checked_by_user_id"] = api.actor()
    store.touch(order)
    return api.ok(serialize.meal_order(order))


@bp.post("/<order_id>/temperature-check")
@api.require("TrayAide")
def temperature_check(order_id):
    order = store.get_meal_order(order_id)
    body = api.body()
    hot = api.opt_num(body, "hot_probe_celsius", None)
    cold = api.opt_num(body, "cold_probe_celsius", None)

    if order["fulfillment_status"] != "PLATED":
        raise ApiError("ERR_INVALID_STATE",
                       "Quality assurance begins once the tray is PLATED.")
    if order["qa_status"] not in ("ACCURACY_PASSED", "TEMP_FAILED"):
        raise ApiError("ERR_INVALID_STATE",
                       "The temperature check cannot be recorded from qa_status %s."
                       % order["qa_status"])
    if api.actor() == order["accuracy_checked_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The temperature check may not be recorded by the user who "
                       "recorded the accuracy check.")
    if order["requires_hot_probe"] and hot is None:
        raise ApiError("ERR_TEMPERATURE_PROBE_REQUIRED",
                       "hot_probe_celsius is required for this tray.")
    if order["requires_cold_probe"] and cold is None:
        raise ApiError("ERR_TEMPERATURE_PROBE_REQUIRED",
                       "cold_probe_celsius is required for this tray.")

    if hot is not None:
        order["hot_probe_celsius"] = calcs.rhu(hot, 1)
    if cold is not None:
        order["cold_probe_celsius"] = calcs.rhu(cold, 1)

    satisfactory = calcs.probes_satisfactory(order, hot, cold)
    if satisfactory:
        order["qa_status"] = "TEMP_PASSED"
    else:
        order["qa_status"] = "TEMP_FAILED"
        order["temperature_retry_count"] += 1
    order["temperature_checked_by_user_id"] = api.actor()
    store.touch(order)
    return api.ok(serialize.meal_order(order))


@bp.post("/<order_id>/deliver")
@api.require("TrayAide")
def deliver(order_id):
    order = store.get_meal_order(order_id)
    patient = store.patients[order["patient_id"]]
    period = store.meal_periods[order["meal_period_id"]]

    if order["fulfillment_status"] != "PLATED":
        raise ApiError("ERR_INVALID_STATE", "Only a PLATED tray may be delivered.")
    if order["qa_status"] != "TEMP_PASSED":
        raise ApiError("ERR_QA_NOT_PASSED",
                       "The tray has not passed its temperature check.")
    if patient["npo_status"] != "NONE":
        raise ApiError("ERR_NPO_ACTIVE", "The patient is under a nil-per-os hold.")

    delivered_at = store.now()
    compliance = calcs.delivery_window_compliance(
        delivered_at, period["window_start_at"], period["window_end_at"])
    order["delivered_at"] = delivered_at
    order["delivery_window_compliance"] = compliance
    order["service_compliance_score"] = calcs.service_compliance_score(
        compliance, order["temperature_retry_count"], order["accuracy_retry_count"])
    order["fulfillment_status"] = "DELIVERED"
    store.touch(order)

    period["delivered_tray_count"] = sum(
        1 for t in store.orders_of_period(period["id"])
        if t["fulfillment_status"] == "DELIVERED")
    store.touch(period)
    return api.ok(serialize.meal_order(order))
