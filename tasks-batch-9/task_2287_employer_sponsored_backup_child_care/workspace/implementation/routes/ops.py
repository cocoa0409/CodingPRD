"""Logical clock and the daily maintenance sweep."""

from flask import Blueprint

from db import db
from errors import ApiError
from middleware import auth, json_body
from response import ok
from util import fmt_dt, parse_dt_value

from services.cascade import run_maintenance

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = json_body()
    if "current_utc" not in body or body["current_utc"] is None:
        raise ApiError("ERR_INVALID_REQUEST")
    target = parse_dt_value(body["current_utc"])
    auth(
        "network_admin",
        "benefits_admin",
        "care_coordinator",
        "provider_manager",
        "employee_user",
    )
    previous = db.current_utc
    if target < previous:
        raise ApiError("ERR_CLOCK_MOVES_BACKWARD")
    db.current_utc = target
    return ok({"current_utc": fmt_dt(target), "previous_utc": fmt_dt(previous)})


@bp.post("/_ops/run-daily-maintenance")
def daily_maintenance():
    json_body()
    auth("network_admin")
    return ok(run_maintenance())
