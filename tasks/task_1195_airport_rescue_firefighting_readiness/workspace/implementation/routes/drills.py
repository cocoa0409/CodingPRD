"""Response drills: schedule, execute, certify, fail."""
from flask import Blueprint, request

from db import store, base_entity, touch, serialize, fmt_ts, fmt_clock
from errors import (
    ApiError, ERR_DRILL_NOT_FOUND, ERR_DRILL_WINDOW_INVALID,
    ERR_DRILL_WINDOW_OVERLAP, ERR_DRILL_NOT_EXECUTABLE, ERR_DRILL_WINDOW_EXPIRED,
    ERR_DRILL_NOT_CERTIFIABLE, ERR_RESPONSE_TIME_EXCEEDED,
)
from middleware import require, json_body, need_str, need_int, need_datetime_str, ALL_ROLES
from response import success, paginated
from services import calc
from db import parse_dt

bp = Blueprint("drills", __name__)


def get_drill_or_404(did):
    d = store.drills.get(did)
    if d is None:
        raise ApiError(ERR_DRILL_NOT_FOUND, 404, "Response drill id does not exist")
    return d


@bp.post("/arff/response-drills")
def create_drill():
    require(["ArffChief"])
    data = json_body()
    runway = need_str(data, "runway_designator", nonempty=True)
    start_raw = need_datetime_str(data, "scheduled_start")
    end_raw = need_datetime_str(data, "scheduled_end")
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    if not start < end:
        raise ApiError(ERR_DRILL_WINDOW_INVALID, 422,
                       "scheduled_start must be strictly before scheduled_end")
    for other in store.drills.values():
        if other["runway_designator"] == runway and other["status"] == "SCHEDULED":
            # half-open [start, end) overlap
            if start < other["_end_dt"] and other["_start_dt"] < end:
                raise ApiError(ERR_DRILL_WINDOW_OVERLAP, 409,
                               "Drill window overlaps a SCHEDULED drill on this runway")
    d = base_entity()
    d.update({
        "runway_designator": runway,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "first_vehicle_arrival_seconds": None,
        "all_vehicles_arrival_seconds": None,
        "executed_at": None,
        "outcome": None,
        "status": "SCHEDULED",
        "_start_dt": start,
        "_end_dt": end,
    })
    store.drills[d["id"]] = d
    return success(serialize(d), "object", 201)


@bp.get("/arff/response-drills")
def list_drills():
    require(ALL_ROLES)
    items = list(store.drills.values())
    runway = request.args.get("runway_designator")
    if runway is not None:
        items = [d for d in items if d["runway_designator"] == runway]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return paginated(items)


@bp.get("/arff/response-drills/<did>")
def get_drill(did):
    require(ALL_ROLES)
    return success(serialize(get_drill_or_404(did)), "object", 200)


@bp.post("/arff/response-drills/<did>/execute")
def execute_drill(did):
    require(["ArffChief"])
    d = get_drill_or_404(did)
    data = json_body()
    first = need_int(data, "first_vehicle_arrival_seconds", min_value=0)
    allv = need_int(data, "all_vehicles_arrival_seconds", min_value=0)
    if d["status"] != "SCHEDULED":
        raise ApiError(ERR_DRILL_NOT_EXECUTABLE, 409, "Drill must be SCHEDULED to execute")
    now = store.clock
    if now < d["_start_dt"]:
        raise ApiError(ERR_DRILL_WINDOW_INVALID, 422,
                       "Logical clock is before scheduled_start")
    if now > d["_end_dt"]:
        raise ApiError(ERR_DRILL_WINDOW_EXPIRED, 422,
                       "Logical clock is after scheduled_end")
    d["first_vehicle_arrival_seconds"] = first
    d["all_vehicles_arrival_seconds"] = allv
    d["executed_at"] = fmt_clock(now)
    d["_executed_dt"] = now
    d["outcome"] = calc.drill_outcome(first, allv)
    d["status"] = "EXECUTED"
    touch(d)
    return success(serialize(d), "object", 200)


@bp.post("/arff/response-drills/<did>/certify")
def certify_drill(did):
    require(["ArffChief"])
    d = get_drill_or_404(did)
    if d["status"] != "EXECUTED":
        raise ApiError(ERR_DRILL_NOT_CERTIFIABLE, 409, "Drill must be EXECUTED to certify")
    if d["outcome"] != "PASS":
        raise ApiError(ERR_RESPONSE_TIME_EXCEEDED, 422,
                       "Drill outcome is FAIL; response-time thresholds exceeded")
    d["status"] = "CERTIFIED"
    touch(d)
    return success(serialize(d), "object", 200)


@bp.post("/arff/response-drills/<did>/fail")
def fail_drill(did):
    require(["ArffChief"])
    d = get_drill_or_404(did)
    if d["status"] != "EXECUTED":
        raise ApiError(ERR_DRILL_NOT_EXECUTABLE, 409, "Drill must be EXECUTED to fail")
    d["status"] = "FAILED"
    touch(d)
    return success(serialize(d), "object", 200)
