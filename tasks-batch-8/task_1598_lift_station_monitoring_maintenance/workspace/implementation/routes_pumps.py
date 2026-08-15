"""Pump routes: register/list/get, status transitions, alternation,
runtime-reading ingestion (PRD 3.2, 3.5)."""
from decimal import Decimal

from flask import Blueprint, request

import db
import services
from envelope import success
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_FIRM_CAPACITY_VIOLATION,
    ERR_DUPLICATE_POSITION,
    ERR_READING_OUT_OF_ORDER,
)
from helpers import (
    body, bad, is_int, req_enum, opt_enum, req_instant, req_int, to_decimal,
    paginate, PUMP_STATUSES, READING_SOURCES, parse_instant,
)
from middleware import require_roles
from routes_stations import get_station_or_404
from serializers import ser_pump, ser_reading

bp = Blueprint("pumps", __name__)

PUMP_READ_ROLES = (
    "UtilityAdmin", "OperationsSupervisor", "OnCallOperator", "Operator",
    "MaintenancePlanner",
)


def get_pump_or_404(pid):
    p = db.pumps.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Pump not found")
    return p


def station_of(pump):
    return db.stations[pump["station_id"]]


@bp.post("/pumps")
def create_pump():
    require_roles("MaintenancePlanner", "UtilityAdmin")
    b = body()
    # body FK existence (priority 5)
    stid = b.get("station_id")
    if stid is None:
        bad("station_id is required")
    if not isinstance(stid, str):
        bad("station_id must be a string")
    st = db.stations.get(stid)
    if st is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "station_id does not resolve")
    # posture gate (priority 7)
    services.check_posture(st)
    # business constraint (priority 12): position range + uniqueness
    pos = b.get("position_index")
    if pos is not None:
        if not is_int(pos):
            bad("position_index must be an integer")
        if pos < 1 or pos > st["pump_count"]:
            raise ApiError(
                ERR_DUPLICATE_POSITION, 422,
                "position_index must be within [1, %d]" % st["pump_count"],
            )
        for p in db.pumps.values():
            if p["station_id"] == stid and p["position_index"] == pos:
                raise ApiError(
                    ERR_DUPLICATE_POSITION, 422,
                    "position_index %d already used at this station" % pos,
                )
    # shape (priority 30)
    if pos is None:
        bad("position_index is required")
    rated = b.get("rated_gpm")
    if not is_int(rated) or rated <= 0:
        bad("rated_gpm must be a positive integer")
    status = opt_enum(b, "status", PUMP_STATUSES, default="IN_SERVICE")
    p = {
        "id": db.new_id(),
        "station_id": stid,
        "position_index": pos,
        "rated_gpm": rated,
        "status": status,
        "cumulative_runtime_hours": Decimal("0.00"),
        "runtime_since_rebuild_hours": Decimal("0.00"),
        "last_alternation_at": None,
        "rebuild_count": 0,
    }
    db.stamp(p)
    db.pumps[p["id"]] = p
    services.sync_station(st)
    return success(ser_pump(p), 201)


@bp.get("/pumps")
def list_pumps():
    require_roles(*PUMP_READ_ROLES)
    items = list(db.pumps.values())
    stid = request.args.get("station_id")
    if stid is not None:
        items = [p for p in items if p["station_id"] == stid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items)
    return success([ser_pump(p) for p in page], 200, meta)


@bp.get("/stations/<sid>/pumps")
def list_station_pumps(sid):
    require_roles(*PUMP_READ_ROLES)
    get_station_or_404(sid)
    items = [p for p in db.pumps.values() if p["station_id"] == sid]
    page, meta = paginate(items)
    return success([ser_pump(p) for p in page], 200, meta)


@bp.get("/pumps/<pid>")
def get_pump(pid):
    require_roles(*PUMP_READ_ROLES)
    return success(ser_pump(get_pump_or_404(pid)))


# --------------------------------------------------------------------- status actions


@bp.post("/pumps/<pid>/standby")
def pump_standby(pid):
    require_roles("OperationsSupervisor")
    p = get_pump_or_404(pid)
    st = station_of(p)
    if p["status"] != "IN_SERVICE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an IN_SERVICE pump can enter STANDBY")
    services.check_posture(st)
    p["status"] = "STANDBY"
    db.touch(p)
    services.sync_station(st)
    return success(ser_pump(p))


@bp.post("/pumps/<pid>/activate")
def pump_activate(pid):
    require_roles("OperationsSupervisor")
    p = get_pump_or_404(pid)
    st = station_of(p)
    if p["status"] not in ("STANDBY", "OUT_OF_SERVICE"):
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only a STANDBY or OUT_OF_SERVICE pump can be activated",
        )
    services.check_posture(st)
    p["status"] = "IN_SERVICE"
    # If activation makes this pump the lead (lowest position_index among
    # IN_SERVICE pumps), stamp last_alternation_at.
    in_service = [
        q for q in db.pumps.values()
        if q["station_id"] == st["id"] and q["status"] == "IN_SERVICE"
    ]
    lead = min(in_service, key=lambda q: (q["position_index"], q["_seq"]))
    if lead["id"] == p["id"]:
        p["last_alternation_at"] = db.now()
    db.touch(p)
    services.sync_station(st)
    return success(ser_pump(p))


@bp.post("/pumps/<pid>/mark-out-of-service")
def pump_mark_out_of_service(pid):
    require_roles("OperationsSupervisor")
    p = get_pump_or_404(pid)
    st = station_of(p)
    if p["status"] != "IN_SERVICE":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only an IN_SERVICE pump can be marked OUT_OF_SERVICE",
        )
    services.check_posture(st)
    in_service = sum(
        1 for q in db.pumps.values()
        if q["station_id"] == st["id"] and q["status"] == "IN_SERVICE"
    )
    if in_service <= 1:
        raise ApiError(
            ERR_FIRM_CAPACITY_VIOLATION, 422,
            "Transition would leave the station without an IN_SERVICE pump",
        )
    p["status"] = "OUT_OF_SERVICE"
    db.touch(p)
    services.auto_alarm(st["id"], "MAJOR", "PUMP_OUT_OF_SERVICE")
    services.sync_station(st)
    return success(ser_pump(p))


# --------------------------------------------------------------------- alternation


@bp.post("/pumps/alternate")
def pump_alternate():
    require_roles("OperationsSupervisor", "UtilityAdmin")
    b = body()
    stid = b.get("station_id")
    if stid is None:
        bad("station_id is required")
    if not isinstance(stid, str):
        bad("station_id must be a string")
    st = db.stations.get(stid)
    if st is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "station_id does not resolve")
    services.check_posture(st)
    result = services.run_alternation(st)
    return success(ser_pump(result))


# --------------------------------------------------------------------- runtime readings


@bp.post("/pumps/<pid>/runtime-readings")
def create_reading(pid):
    require_roles("Operator", "ScadaWebhook", "UtilityAdmin")
    p = get_pump_or_404(pid)
    st = station_of(p)
    # posture gate (child mutation of the station via its pump)
    services.check_posture(st)
    # recorded_at must be parsed before the chronological check can run
    b = body()
    recorded = req_instant(b, "recorded_at")
    # temporal (priority 19): no out-of-order readings for the same pump
    prior = [
        r for r in db.runtime_readings.values() if r["pump_id"] == pid
    ]
    if prior:
        latest = max(r["recorded_at"] for r in prior)
        if recorded < latest:
            raise ApiError(
                ERR_READING_OUT_OF_ORDER, 422,
                "recorded_at precedes the prior reading for this pump",
            )
    # shape (priority 30)
    delta_raw = b.get("run_hours_delta")
    if delta_raw is None:
        bad("run_hours_delta is required")
    delta = to_decimal(delta_raw, "run_hours_delta", 2)
    if delta < Decimal("0") or delta > Decimal("24"):
        bad("run_hours_delta must be in [0, 24]")
    starts = b.get("starts_count")
    if not is_int(starts) or starts < 0:
        bad("starts_count must be a non-negative integer")
    source = req_enum(b, "source", READING_SOURCES)
    r = {
        "id": db.new_id(),
        "pump_id": pid,
        "recorded_at": recorded,
        "run_hours_delta": delta,
        "starts_count": starts,
        "source": source,
        "created_at": db.now(),
        "_seq": db.next_seq(),
    }
    db.runtime_readings[r["id"]] = r
    p["cumulative_runtime_hours"] += delta
    p["runtime_since_rebuild_hours"] += delta
    db.touch(p)
    return success(ser_reading(r), 201)


@bp.get("/pumps/<pid>/runtime-readings")
def list_readings(pid):
    require_roles(*PUMP_READ_ROLES)
    get_pump_or_404(pid)
    items = [r for r in db.runtime_readings.values() if r["pump_id"] == pid]
    since = request.args.get("since")
    if since is not None:
        since_dt = parse_instant(since, "since")
        items = [r for r in items if r["recorded_at"] >= since_dt]
    until = request.args.get("until")
    if until is not None:
        until_dt = parse_instant(until, "until")
        items = [r for r in items if r["recorded_at"] <= until_dt]
    page, meta = paginate(items)
    return success([ser_reading(r) for r in page], 200, meta)
