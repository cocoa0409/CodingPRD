"""On-air milestone planning, schedule forecasting and activation."""

from flask import Blueprint

import services
from db import db, fmt_dt, get_dt, new_record, now, serialize, set_dt, whole_days
from errors import ApiError
from response import created, ok
from routes.common import fetch, listing
from validation import (ALL_ROLES, DATETIME, ROLE_CONSTRUCTION, ROLE_DIRECTOR,
                        STRING, authenticate, f, validate_body)

bp = Blueprint("onair", __name__)

FORECASTABLE = ("PLANNED", "AT_RISK", "RESET")


@bp.post("/on-air-plans")
def create_plan():
    authenticate([ROLE_DIRECTOR])
    body = validate_body([
        f("search_ring_id", STRING),
        f("target_on_air_date", DATETIME),
    ])
    ring = db.search_rings.get(body["search_ring_id"])
    if ring is None:
        raise ApiError("ERR_SEARCH_RING_NOT_FOUND", 404)

    target = body["target_on_air_date"]
    forecast = services.compute_forecast(ring, target.dt)

    plan = new_record({
        "search_ring_id": ring["id"],
        "target_on_air_date": target.raw,
        "baseline_forecast_date": fmt_dt(forecast["baseline_date"]),
        "risk_adjusted_forecast_date": fmt_dt(forecast["risk_date"]),
        "schedule_risk_score": forecast["schedule_risk_score"],
        "risk_band": forecast["risk_band"],
        "driver_candidate_id": forecast["driver_candidate_id"],
        "status": "PLANNED",
        "actual_on_air_date": None,
        "variance_days": None,
        "reset_count": 0,
    })
    set_dt(plan, "target_on_air_date", target.dt, raw=target.raw)
    set_dt(plan, "baseline_forecast_date", forecast["baseline_date"])
    set_dt(plan, "risk_adjusted_forecast_date", forecast["risk_date"])
    set_dt(plan, "actual_on_air_date", None)
    db.on_air_plans[plan["id"]] = plan
    return created(serialize(plan))


@bp.get("/on-air-plans")
def list_plans():
    authenticate(ALL_ROLES)
    return listing("on_air_plans", ["search_ring_id", "status", "risk_band"])


@bp.get("/on-air-plans/<plan_id>")
def read_plan(plan_id):
    authenticate(ALL_ROLES)
    return ok(serialize(fetch("on_air_plans", plan_id)))


def _ring_of(plan):
    ring = db.search_rings.get(plan["search_ring_id"])
    if ring is None:
        raise ApiError("ERR_SEARCH_RING_NOT_FOUND", 404)
    return ring


@bp.post("/on-air-plans/<plan_id>/reforecast")
def reforecast(plan_id):
    authenticate([ROLE_DIRECTOR])
    validate_body([])
    plan = fetch("on_air_plans", plan_id)
    if plan["status"] not in FORECASTABLE:
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    ring = _ring_of(plan)
    forecast = services.compute_forecast(ring, get_dt(plan, "target_on_air_date"),
                                         plan=plan)
    status = "AT_RISK" if forecast["risk_band"] == "HIGH" else "PLANNED"
    services.write_forecast(plan, forecast, {"status": status})
    return ok(serialize(plan))


@bp.post("/on-air-plans/<plan_id>/reset")
def reset_plan(plan_id):
    authenticate([ROLE_DIRECTOR])
    body = validate_body([
        f("new_target_on_air_date", DATETIME),
        f("reason", STRING),
    ])
    plan = fetch("on_air_plans", plan_id)
    if plan["status"] not in ("PLANNED", "AT_RISK"):
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    target = body["new_target_on_air_date"]
    if target.dt <= now():
        raise ApiError("ERR_TARGET_DATE_IN_PAST", 422)

    ring = _ring_of(plan)
    forecast = services.compute_forecast(ring, target.dt, plan=plan, strict=False)
    set_dt(plan, "target_on_air_date", target.dt, raw=target.raw)
    services.write_forecast(plan, forecast, {
        "target_on_air_date": target.raw,
        "reset_count": plan["reset_count"] + 1,
        "status": "RESET",
    })
    return ok(serialize(plan))


@bp.post("/on-air-plans/<plan_id>/activate")
def activate(plan_id):
    authenticate([ROLE_CONSTRUCTION])
    body = validate_body([f("actual_on_air_date", DATETIME)])
    plan = fetch("on_air_plans", plan_id)

    if plan["status"] not in FORECASTABLE:
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)
    ring = _ring_of(plan)
    if ring["status"] != "SITE_SELECTED" or ring["selected_candidate_id"] is None:
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    candidate = db.candidates.get(ring["selected_candidate_id"])
    if candidate is not None:
        services.refresh_candidate_permits(candidate["id"])
    if candidate is None or candidate["feasibility_status"] != "BUILD_READY":
        raise ApiError("ERR_CANDIDATE_NOT_BUILD_READY", 409)
    if not services.has_delivered_power_and_fiber(candidate["id"]):
        raise ApiError("ERR_BACKHAUL_NOT_DELIVERED", 409)

    actual = body["actual_on_air_date"]
    if actual.dt > now():
        raise ApiError("ERR_DATE_IN_FUTURE", 422)

    target = get_dt(plan, "target_on_air_date")
    variance = whole_days(actual.dt, target) if target is not None else None
    set_dt(plan, "actual_on_air_date", actual.dt, raw=actual.raw)
    services.apply(plan, {
        "actual_on_air_date": actual.raw,
        "variance_days": variance,
        "status": "ON_AIR",
    })
    services.apply(ring, {"status": "ON_AIR"})
    return ok(serialize(plan))


@bp.get("/on-air-plans/<plan_id>/forecast")
def read_forecast(plan_id):
    authenticate([ROLE_DIRECTOR, ROLE_CONSTRUCTION])
    plan = fetch("on_air_plans", plan_id)
    ring = _ring_of(plan)
    forecast = services.compute_forecast(ring, get_dt(plan, "target_on_air_date"),
                                         plan=plan, strict=False)
    return ok({
        "baseline_forecast_date": fmt_dt(forecast["baseline_date"]),
        "risk_adjusted_forecast_date": fmt_dt(forecast["risk_date"]),
        "remaining_days": forecast["remaining_days"],
        "risk_days": forecast["risk_days"],
        "schedule_risk_score": forecast["schedule_risk_score"],
        "risk_band": forecast["risk_band"],
        "slip_days": forecast["slip_days"],
        "driver_candidate_id": forecast["driver_candidate_id"],
    })
