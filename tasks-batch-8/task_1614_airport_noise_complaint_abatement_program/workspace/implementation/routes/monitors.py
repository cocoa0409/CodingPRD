"""Noise monitors, outages, event ingestion, DNL read (PRD §3.3)."""
from flask import Blueprint, request

from db import db, new_id
from errors import err
from middleware import get_caller, require_role, get_body
from response import success_object, success_list
from serialize import ser_monitor, ser_outage, ser_event
import services
from services import touch
from util import now, parse_date, quarter_key_of
from validate import validate, parse_pagination

bp = Blueprint("monitors", __name__)

STAFF = ["NoiseOfficeAdmin", "NoiseAnalyst", "CommunityLiaison",
         "StudyCoordinator", "BoardMember"]

OUTAGE_TYPES = ["CALIBRATION", "MAINTENANCE", "FAULT"]


def _get_monitor(mid):
    m = db.monitors.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", f"NoiseMonitor {mid} not found")
    return m


@bp.post("/noise-monitors")
def create_monitor():
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("station_code", "str", True),
        ("zone_code", "str", True),
        ("latitude", "num", True),
        ("longitude", "num", True),
        ("commissioned_at", "dt", True),
    ])
    require_role(caller, ["NoiseOfficeAdmin"])
    for m in db.monitors.values():
        if m["station_code"] == data["station_code"]:
            raise err("ERR_DUPLICATE_STATION_CODE",
                      f"station_code {data['station_code']} is already registered")
    t = now()
    m = {
        "id": new_id(),
        "station_code": data["station_code"],
        "zone_code": data["zone_code"],
        "latitude": data["latitude"],
        "longitude": data["longitude"],
        "commissioned_at": data["commissioned_at"],
        "status": "ONLINE",
        "events_captured_total": 0,
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.monitors[m["id"]] = m
    return success_object(ser_monitor(m), status=201)


@bp.get("/noise-monitors")
def list_monitors():
    caller = get_caller()
    require_role(caller, STAFF)
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    zone = request.args.get("zone_code")
    items = sorted(db.monitors.values(), key=lambda m: m["created_at"])
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if zone is not None:
        items = [m for m in items if m["zone_code"] == zone]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_monitor(m) for m in page], limit, offset, total)


@bp.get("/noise-monitors/<monitorId>")
def get_monitor(monitorId):
    caller = get_caller()
    require_role(caller, STAFF)
    m = _get_monitor(monitorId)
    return success_object(ser_monitor(m))


@bp.post("/noise-monitors/<monitorId>/outages")
def create_outage(monitorId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("start_at", "dt", True),
        ("end_at", "dt", True),
        ("outage_type", "enum", True, {"enum": OUTAGE_TYPES}),
        ("reason", "str", False),
    ])
    if data["end_at"] <= data["start_at"]:
        raise err("ERR_VALIDATION", "end_at must be strictly after start_at")
    require_role(caller, ["NoiseOfficeAdmin"])
    m = _get_monitor(monitorId)
    for o in db.outages.values():
        if o["monitor_id"] != m["id"]:
            continue
        # half-open intervals: adjacency allowed, positive intersection rejected
        if data["start_at"] < o["end_at"] and o["start_at"] < data["end_at"]:
            raise err("ERR_OUTAGE_OVERLAP",
                      "Outage overlaps an existing outage on this monitor")
    o = {
        "id": new_id(),
        "monitor_id": m["id"],
        "start_at": data["start_at"],
        "end_at": data["end_at"],
        "outage_type": data["outage_type"],
        "reason": data.get("reason"),
        "created_at": now(),
    }
    db.outages[o["id"]] = o
    return success_object(ser_outage(o), status=201)


@bp.get("/noise-monitors/<monitorId>/outages")
def list_outages(monitorId):
    caller = get_caller()
    require_role(caller, STAFF)
    m = _get_monitor(monitorId)
    limit, offset = parse_pagination(request.args)
    items = sorted((o for o in db.outages.values() if o["monitor_id"] == m["id"]),
                   key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_outage(o) for o in page], limit, offset, total)


@bp.post("/noise-monitors/<monitorId>/decommission")
def decommission_monitor(monitorId):
    caller = get_caller()
    get_body()
    require_role(caller, ["NoiseOfficeAdmin"])
    m = _get_monitor(monitorId)
    if m["status"] != "ONLINE":
        raise err("ERR_MONITOR_NOT_ONLINE", "Monitor is not ONLINE")
    m["status"] = "DECOMMISSIONED"
    touch(m)
    return success_object(ser_monitor(m))


@bp.post("/noise-monitors/<monitorId>/events")
def ingest_event(monitorId):
    caller = get_caller()
    body = get_body()
    data = validate(body, [
        ("started_at", "dt", True),
        ("duration_seconds", "int", True, {"min": 5}),
        ("lmax_db", "num", True),
        ("sel_db", "num", True),
    ])
    require_role(caller, ["NoiseOfficeAdmin"])
    m = _get_monitor(monitorId)
    if m["status"] != "ONLINE":
        raise err("ERR_MONITOR_NOT_ONLINE",
                  "Cannot ingest events into a decommissioned monitor")
    start = data["started_at"]
    from datetime import timedelta
    end = start + timedelta(seconds=data["duration_seconds"])
    for o in db.outages.values():
        if o["monitor_id"] != m["id"]:
            continue
        if start < o["end_at"] and o["start_at"] < end:
            raise err("ERR_EVENT_DURING_OUTAGE",
                      "Event interval overlaps a recorded outage on this monitor")
    t = now()
    e = {
        "id": new_id(),
        "monitor_id": m["id"],
        "started_at": start,
        "duration_seconds": data["duration_seconds"],
        "lmax_db": data["lmax_db"],
        "sel_db": data["sel_db"],
        "status": "CAPTURED",
        "flight_id": None,
        "classification_basis": None,
        "classification_confidence": 0,
        "reclassify_count": 0,
        "exceeds_threshold": data["lmax_db"] >= 65.0,
        "quarter_key": quarter_key_of(start),
        "created_at": t,
        "updated_at": t,
        "version": 1,
    }
    db.events[e["id"]] = e
    m["events_captured_total"] += 1
    touch(m)
    return success_object(ser_event(e), status=201)


@bp.get("/noise-monitors/<monitorId>/dnl")
def monitor_dnl(monitorId):
    caller = get_caller()
    require_role(caller, STAFF)
    m = _get_monitor(monitorId)
    day = parse_date(request.args.get("date"))
    if day is None:
        raise err("ERR_VALIDATION", "date query parameter must be YYYY-MM-DD")
    return success_object(services.dnl_for_date(m["id"], day))
