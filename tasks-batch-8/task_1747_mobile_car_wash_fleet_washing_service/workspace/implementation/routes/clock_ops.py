"""Test-driving clock, daily sweep, and weather evaluation endpoints."""

from datetime import timedelta

from flask import Blueprint

from db import store
from services import weather_freeze, cancel_order
from util import (
    caller, require_role, get_body, respond, now, clock_date, iso_dt, iso_d,
    parse_dt, parse_date, req_int, touch, ApiError,
)
from errors import ERR_VALIDATION

bp = Blueprint("clock_ops", __name__)


@bp.post("/fleet-wash/_clock/set_current_utc")
def set_clock():
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    to = parse_dt(body.get("to_iso8601"), "to_iso8601")
    store.clock = to
    return respond({"current_utc": iso_dt(store.clock)}, 200)


@bp.post("/fleet-wash/ops/run-daily")
def run_daily():
    _uid, role = caller()
    require_role(role, {"Dispatcher"})
    closed_ids = []
    close_threshold = now() - timedelta(hours=72)
    for order in sorted(store.orders.values(), key=lambda r: r["_seq"]):
        if order["status"] == "COMPLETED" and order["completed_at"] is not None \
                and order["completed_at"] <= close_threshold:
            order["status"] = "CLOSED"
            touch(order)
            closed_ids.append(order["id"])
    expired_ids = []
    cd = clock_date()
    for order in sorted(store.orders.values(), key=lambda r: r["_seq"]):
        if order["status"] == "WEATHER_HELD" and order["held_at"] is not None \
                and order["held_at"].date() + timedelta(days=14) < cd:
            cancel_order(order, "WEATHER_EXPIRED")
            expired_ids.append(order["id"])
    return respond({"closed_order_ids": closed_ids, "expired_order_ids": expired_ids}, 200)


@bp.post("/fleet-wash/weather/evaluations")
def weather_evaluation():
    _uid, role = caller()
    require_role(role, {"Dispatcher"})
    body = get_body()
    eval_date = parse_date(body.get("evaluation_date"), "evaluation_date")
    low = req_int(body, "forecast_low_f")
    precip = req_int(body, "precip_probability_pct")
    if precip < 0 or precip > 100:
        raise ApiError(ERR_VALIDATION, "precip_probability_pct must be between 0 and 100")
    freeze = low <= 32
    advisory = False
    cancelled, held = [], []
    if freeze:
        cancelled, held = weather_freeze(eval_date)
    elif precip >= 60:
        advisory = True
    return respond({
        "evaluation_date": iso_d(eval_date),
        "freeze": freeze,
        "advisory": advisory,
        "cancelled_route_ids": cancelled,
        "held_order_ids": held,
    }, 201)
