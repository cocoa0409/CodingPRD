"""Vehicles, readiness checks, and out-of-service events."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, base_entity, touch, serialize, fmt_ts, fmt_clock
from errors import (
    ApiError, ERR_VEHICLE_NOT_FOUND, ERR_DUPLICATE_CALL_SIGN,
    ERR_MEASURED_EXCEEDS_CAPACITY, ERR_VEHICLE_ALREADY_OUT_OF_SERVICE,
    ERR_OOS_EVENT_NOT_FOUND, ERR_OOS_EVENT_NOT_OPEN, ERR_READINESS_RECHECK_REQUIRED,
)
from middleware import require, json_body, need_str, need_number, need_bool, ALL_ROLES
from response import success, paginated
from services import calc

bp = Blueprint("fleet", __name__)


def get_vehicle_or_404(vid):
    v = store.vehicles.get(vid)
    if v is None:
        raise ApiError(ERR_VEHICLE_NOT_FOUND, 404, "Vehicle id does not exist")
    return v


@bp.post("/arff/vehicles")
def create_vehicle():
    require(["ArffChief"])
    data = json_body()
    cs = need_str(data, "call_sign", nonempty=True)
    wc = need_number(data, "water_capacity_gal", min_value=0, exclusive_min=True)
    dc = need_number(data, "dry_chem_capacity_lb", min_value=0)
    if any(v["call_sign"] == cs for v in store.vehicles.values()):
        raise ApiError(ERR_DUPLICATE_CALL_SIGN, 409, "Vehicle call_sign already in use")
    v = base_entity()
    v.update({
        "call_sign": cs,
        "water_capacity_gal": wc,
        "dry_chem_capacity_lb": dc,
        "status": "IN_SERVICE",
        "latest_readiness_result": "NONE",
        "open_oos_event_id": None,
    })
    store.vehicles[v["id"]] = v
    calc.recompute_profile(bump="if_changed")
    return success(serialize(v), "object", 201)


@bp.get("/arff/vehicles")
def list_vehicles():
    require(ALL_ROLES)
    items = list(store.vehicles.values())
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return paginated(items)


@bp.get("/arff/vehicles/<vid>")
def get_vehicle(vid):
    require(ALL_ROLES)
    return success(serialize(get_vehicle_or_404(vid)), "object", 200)


@bp.get("/arff/vehicles/<vid>/readiness-checks")
def list_vehicle_checks(vid):
    require(ALL_ROLES)
    get_vehicle_or_404(vid)
    items = [c for c in store.readiness_checks.values() if c["vehicle_id"] == vid]
    return paginated(items)


@bp.get("/arff/vehicles/<vid>/out-of-service-events")
def list_vehicle_oos(vid):
    require(ALL_ROLES)
    get_vehicle_or_404(vid)
    items = [e for e in store.oos_events.values() if e["vehicle_id"] == vid]
    return paginated(items)


@bp.post("/arff/readiness-checks")
def create_readiness_check():
    require(["ArffChief"])
    data = json_body()
    raw_vid = data.get("vehicle_id")
    if isinstance(raw_vid, str) and raw_vid not in store.vehicles:
        raise ApiError(ERR_VEHICLE_NOT_FOUND, 404, "Vehicle id does not exist")
    vid = need_str(data, "vehicle_id")
    wa = need_number(data, "water_available_gal", min_value=0)
    dca = need_number(data, "dry_chem_available_lb", min_value=0)
    ok = need_bool(data, "discharge_system_ok")
    v = store.vehicles[vid]
    if Decimal(str(wa)) > Decimal(str(v["water_capacity_gal"])) \
            or Decimal(str(dca)) > Decimal(str(v["dry_chem_capacity_lb"])):
        raise ApiError(ERR_MEASURED_EXCEEDS_CAPACITY, 422,
                       "Measured quantity exceeds the vehicle's rated capacity")
    c = base_entity()
    result = "PASS" if (ok and Decimal(str(wa)) > 0) else "FAIL"
    c.update({
        "vehicle_id": vid,
        "water_available_gal": wa,
        "dry_chem_available_lb": dca,
        "discharge_system_ok": ok,
        "checked_at": fmt_clock(store.clock),
        "result": result,
        "_checked_dt": store.clock,
    })
    store.readiness_checks[c["id"]] = c
    latest = calc.latest_check(vid)
    v["latest_readiness_result"] = latest["result"] if latest is not None else "NONE"
    touch(v)
    calc.recompute_profile(bump="always")
    return success(serialize(c), "object", 201)


@bp.post("/arff/vehicles/<vid>/out-of-service-events")
def open_oos_event(vid):
    require(["ArffChief"])
    v = get_vehicle_or_404(vid)
    data = json_body()
    reason = need_str(data, "reason")
    if v["status"] != "IN_SERVICE":
        raise ApiError(ERR_VEHICLE_ALREADY_OUT_OF_SERVICE, 409,
                       "Vehicle is already OUT_OF_SERVICE")
    e = base_entity()
    e.update({
        "vehicle_id": vid,
        "reason": reason,
        "started_at": fmt_clock(store.clock),
        "restored_at": None,
        "status": "OPEN",
        "_started_dt": store.clock,
    })
    store.oos_events[e["id"]] = e
    v["status"] = "OUT_OF_SERVICE"
    v["open_oos_event_id"] = e["id"]
    touch(v)
    calc.recompute_profile(bump="always")
    return success(serialize(e), "object", 201)


@bp.post("/arff/out-of-service-events/<eid>/restore")
def restore_oos_event(eid):
    require(["ArffChief"])
    e = store.oos_events.get(eid)
    if e is None:
        raise ApiError(ERR_OOS_EVENT_NOT_FOUND, 404, "Out-of-service event id does not exist")
    if e["status"] != "OPEN":
        raise ApiError(ERR_OOS_EVENT_NOT_OPEN, 409, "Out-of-service event is not OPEN")
    vid = e["vehicle_id"]
    recheck = any(
        c["vehicle_id"] == vid and c["result"] == "PASS"
        and c["_checked_dt"] >= e["_started_dt"]
        for c in store.readiness_checks.values()
    )
    if not recheck:
        raise ApiError(ERR_READINESS_RECHECK_REQUIRED, 422,
                       "A PASS readiness check at-or-after the event start is required")
    e["status"] = "RESTORED"
    e["restored_at"] = fmt_clock(store.clock)
    touch(e)
    v = store.vehicles[vid]
    v["status"] = "IN_SERVICE"
    v["open_oos_event_id"] = None
    touch(v)
    calc.recompute_profile(bump="always")
    return success(serialize(e), "object", 200)
