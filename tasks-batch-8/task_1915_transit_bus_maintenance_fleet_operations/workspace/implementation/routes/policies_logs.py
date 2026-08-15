"""PM policy and mileage/fuel log routes."""
from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, body, req_int, req_date, opt_str,
                     paginate, sort_default, success)
from store import db, init_common, mark_dirty, fmt_date, clock_date
from services import domain as dom
from services import serializers as ser
from routes.buses import get_bus_or_404, ALL

bp = Blueprint("policies_logs", __name__)


# ---------------------------------------------------------------------------
# PM policies
# ---------------------------------------------------------------------------
@bp.post("/fleet/pm-policies")
def create_policy():
    require_roles("FleetManager")
    data = body()
    a = req_int(data, "level_a_interval_miles")
    b = req_int(data, "level_b_interval_miles")
    c = req_int(data, "level_c_interval_miles")
    tol = req_int(data, "tolerance_miles")
    cal = req_int(data, "calendar_interval_days")
    if (a <= 0 or b <= 0 or c <= 0 or b % a != 0 or c % b != 0
            or tol < 0 or tol >= a):
        raise err("ERR_PM_POLICY_INVALID",
                  "PM intervals must nest as positive multiples and "
                  "tolerance_miles must be < level A interval")
    # supersede prior ACTIVE policy
    for p in db["pm_policies"].values():
        if p["status"] == "ACTIVE":
            p["status"] = "SUPERSEDED"
            mark_dirty("pm_policies", p["id"])
    policy = init_common({
        "level_a_interval_miles": a,
        "level_b_interval_miles": b,
        "level_c_interval_miles": c,
        "tolerance_miles": tol,
        "calendar_interval_days": cal,
        "status": "ACTIVE",
    })
    db["pm_policies"][policy["id"]] = policy
    dom.recompute_pm_due_all(policy)
    return success(ser.pm_policy(policy), code=201)


@bp.get("/fleet/pm-policies/<pid>")
def get_policy(pid):
    require_roles(*ALL)
    p = db["pm_policies"].get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", f"PMPolicy {pid} not found")
    return success(ser.pm_policy(p))


@bp.get("/fleet/pm-policies")
def list_policies():
    require_roles(*ALL)
    items = list(db["pm_policies"].values())
    st = request.args.get("status")
    if st is not None:
        items = [p for p in items if p["status"] == st]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.pm_policy(p) for p in page], response_type="array",
                   pagination=meta_p)


# ---------------------------------------------------------------------------
# Mileage / fuel logs
# ---------------------------------------------------------------------------
@bp.post("/fleet/mileage-fuel-logs")
def create_log():
    uid, _ = require_roles("Operator")
    data = body()
    bus_id = data.get("bus_id")
    bus = None
    if bus_id is not None:
        bus = db["buses"].get(bus_id)
        if bus is None:
            raise err("ERR_NOT_FOUND", f"Bus {bus_id} not found")
    if bus_id is None:
        raise err("ERR_VALIDATION", "Missing required field: bus_id")
    log_date = req_date(data, "log_date")
    odometer_end = req_int(data, "odometer_end")
    fuel = req_int(data, "fuel_gallons")
    if odometer_end < 0:
        raise err("ERR_VALIDATION", "odometer_end must be >= 0")
    if fuel <= 0:
        raise err("ERR_VALIDATION", "fuel_gallons must be > 0")
    # temporal checks (priority order: regression before future-date)
    if odometer_end <= bus["odometer_miles"]:
        raise err("ERR_ODOMETER_REGRESSION",
                  "odometer_end must be greater than the current odometer")
    if log_date > clock_date():
        raise err("ERR_LOG_DATE_IN_FUTURE",
                  "log_date must not be after the logical clock date")
    if bus["service_status"] == "RETIRED":
        raise err("ERR_BUS_RETIRED", "Referenced bus is RETIRED")

    miles_driven = odometer_end - bus["odometer_miles"]
    log = init_common({
        "bus_id": bus["id"],
        "log_date": fmt_date(log_date),
        "odometer_end": odometer_end,
        "fuel_gallons": fuel,
        "miles_driven": miles_driven,
        "status": "POSTED",
    })
    db["logs"][log["id"]] = log

    bus["odometer_miles"] = odometer_end
    dom.recompute_pm_due(bus)
    mark_dirty("buses", bus["id"])

    # Fuel MPG anomaly check
    if dom.check_fuel_anomaly(log):
        log["status"] = "FLAGGED"
        defect = init_common({
            "bus_id": bus["id"],
            "reported_by": uid,
            "severity": "MAJOR",
            "defect_code": "FUEL_SYSTEM",
            "description": "Fuel economy anomaly detected by mileage/fuel log",
            "odometer_at_report": odometer_end,
            "status": "OPEN",
            "disposition": None,
            "road_call_mechanic_id": None,
            "defer_until_date": None,
            "defer_justification": None,
            "defer_count": 0,
            "linked_work_order_id": None,
            "resolution": None,
            "flagged_by_log_id": log["id"],
        })
        db["defects"][defect["id"]] = defect
        dom.recompute_bus_availability(bus)
        dom.recompute_posture()
    return success(ser.mileage_log(log), code=201)


@bp.get("/fleet/mileage-fuel-logs/<log_id>")
def get_log(log_id):
    require_roles(*ALL)
    log = db["logs"].get(log_id)
    if log is None:
        raise err("ERR_NOT_FOUND", f"MileageFuelLog {log_id} not found")
    return success(ser.mileage_log(log))


@bp.get("/fleet/mileage-fuel-logs")
def list_logs():
    require_roles(*ALL)
    items = list(db["logs"].values())
    bus_id = request.args.get("bus_id")
    if bus_id is not None:
        items = [l for l in items if l["bus_id"] == bus_id]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.mileage_log(l) for l in page], response_type="array",
                   pagination=meta_p)


@bp.get("/fleet/mileage-fuel-logs/<log_id>/defect-reports")
def log_defects(log_id):
    require_roles(*ALL)
    log = db["logs"].get(log_id)
    if log is None:
        raise err("ERR_NOT_FOUND", f"MileageFuelLog {log_id} not found")
    items = [d for d in db["defects"].values()
             if d.get("flagged_by_log_id") == log_id]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.defect(d) for d in page], response_type="array",
                   pagination=meta_p)


@bp.post("/fleet/mileage-fuel-logs/<log_id>/void")
def void_log(log_id):
    require_roles("FleetManager")
    log = db["logs"].get(log_id)
    if log is None:
        raise err("ERR_NOT_FOUND", f"MileageFuelLog {log_id} not found")
    data = body()
    void_reason = opt_str(data, "void_reason")
    if log["status"] == "VOIDED":
        raise err("ERR_ALREADY_TERMINAL", "Log is already VOIDED")
    bus = db["buses"].get(log["bus_id"])
    # must be the latest non-voided log for its bus (log_date DESC, created DESC)
    candidates = [l for l in db["logs"].values()
                  if l["bus_id"] == log["bus_id"] and l["status"] != "VOIDED"]
    candidates.sort(key=lambda l: (l["log_date"], l["created_at"], l["_seq"]),
                    reverse=True)
    if not candidates or candidates[0]["id"] != log["id"]:
        raise err("ERR_LOG_NOT_LATEST",
                  "Only the latest non-voided log for the bus may be voided")
    log["status"] = "VOIDED"
    if void_reason is not None:
        log["void_reason"] = void_reason
    mark_dirty("logs", log["id"])
    # odometer recompute from remaining logs
    remaining = [l for l in db["logs"].values()
                 if l["bus_id"] == log["bus_id"] and l["status"] != "VOIDED"]
    if remaining:
        bus["odometer_miles"] = max(l["odometer_end"] for l in remaining)
    else:
        bus["odometer_miles"] = bus["initial_odometer_miles"]
    dom.recompute_pm_due(bus)
    mark_dirty("buses", bus["id"])
    # auto-created defect still OPEN -> WITHDRAWN (AUTO_VOIDED)
    for d in db["defects"].values():
        if d.get("flagged_by_log_id") == log["id"] and d["status"] == "OPEN":
            d["status"] = "WITHDRAWN"
            d["resolution"] = "AUTO_VOIDED"
            mark_dirty("defects", d["id"])
    dom.recompute_bus_availability(bus)
    dom.recompute_posture()
    return success(ser.mileage_log(log))
