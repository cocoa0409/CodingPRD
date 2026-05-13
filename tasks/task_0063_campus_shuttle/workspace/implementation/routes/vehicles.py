"""Vehicles endpoints."""
from flask import Blueprint, request

import db
from clock import iso, now
from errors import err
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services.util import parse_dt, intervals_overlap_closed_closed


bp = Blueprint("vehicles", __name__)


VALID_TYPES = {"STANDARD", "ELECTRIC", "SHUTTLE_VAN"}


def _serialize(v):
    return {k: x for k, x in v.items() if not k.startswith("_")}


def _plate_unique_active_maintenance(plate: str, exclude_id=None) -> bool:
    for v in db.vehicles.values():
        if exclude_id and v["id"] == exclude_id:
            continue
        if v.get("status") in ("ACTIVE", "MAINTENANCE") and v.get("plate_number") == plate:
            return False
    return True


def _validate_create(body):
    plate = body.get("plate_number")
    cap = body.get("seat_capacity")
    vt = body.get("vehicle_type")
    if not isinstance(plate, str) or not plate.strip():
        raise err("ERR_VALIDATION", "plate_number is required")
    if not isinstance(cap, int) or isinstance(cap, bool):
        raise err("ERR_VALIDATION", "seat_capacity must be integer")
    if not (8 <= cap <= 80):
        raise err("ERR_VALIDATION", "seat_capacity must be in [8,80]")
    if vt not in VALID_TYPES:
        raise err("ERR_VALIDATION", f"vehicle_type must be in {sorted(VALID_TYPES)}")
    if not _plate_unique_active_maintenance(plate):
        raise err("ERR_INVALID_STATE",
                  f"plate_number {plate} already used by an active/maintenance vehicle")


@bp.route("/shuttle/vehicles", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def create_vehicle():
    body = get_json_body()
    _validate_create(body)

    v = {
        "plate_number": body["plate_number"],
        "seat_capacity": int(body["seat_capacity"]),
        "vehicle_type": body["vehicle_type"],
        "status": "ACTIVE",
        "maintenance_window_start": None,
        "maintenance_window_end": None,
        "last_run_completed_at": None,
    }
    db.stamp_create(v)
    db.vehicles[v["id"]] = v
    return success(_serialize(v), status=201)


@bp.route("/shuttle/vehicles", methods=["GET"])
@require_auth(roles={"Dispatcher", "Driver", "Auditor"})
def list_vehicles():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = list(db.vehicles.values())
    if status_filter:
        items = [v for v in items if v.get("status") == status_filter]
    items.sort(key=lambda v: v.get("_seq", 0))
    page = items[offset:offset + limit]
    return success_list([_serialize(v) for v in page], limit, offset, len(items))


@bp.route("/shuttle/vehicles/<vid>/maintenance", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def start_maintenance(vid):
    v = db.vehicles.get(vid)
    if not v:
        raise err("ERR_NOT_FOUND", "Vehicle not found")
    if v.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  f"Cannot start maintenance from status {v.get('status')}")

    body = get_json_body()
    s = body.get("maintenance_window_start")
    e = body.get("maintenance_window_end")
    if s is None or e is None:
        raise err("ERR_VALIDATION",
                  "maintenance_window_start/maintenance_window_end required")
    dt_s = parse_dt(s, "maintenance_window_start")
    dt_e = parse_dt(e, "maintenance_window_end")
    if dt_s >= dt_e:
        raise err("ERR_VALIDATION",
                  "maintenance_window_start must be strictly before end")

    # Check no PLANNED/BOARDING/IN_TRANSIT/DELAYED run-sheet whose occupation window
    # [scheduled_departure - 15m, scheduled_arrival + 15m] overlaps [s, e)
    from datetime import timedelta
    for rs in db.run_sheets.values():
        if rs.get("assigned_vehicle_id") != vid:
            continue
        if rs.get("status") not in ("PLANNED", "BOARDING", "IN_TRANSIT", "DELAYED"):
            continue
        sd = parse_dt(rs["scheduled_departure"]) - timedelta(minutes=15)
        sa = parse_dt(rs["scheduled_arrival"]) + timedelta(minutes=15)
        # Overlap with [dt_s, dt_e)
        if not (sa < dt_s or sd >= dt_e):
            raise err("ERR_VEHICLE_HAS_BOOKED_RUNS",
                      "Vehicle has booked runs overlapping maintenance window")

    v["status"] = "MAINTENANCE"
    v["maintenance_window_start"] = iso(dt_s)
    v["maintenance_window_end"] = iso(dt_e)
    db.stamp_update(v)
    return success(_serialize(v))


@bp.route("/shuttle/vehicles/<vid>/maintenance-complete", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def end_maintenance(vid):
    v = db.vehicles.get(vid)
    if not v:
        raise err("ERR_NOT_FOUND", "Vehicle not found")
    if v.get("status") != "MAINTENANCE":
        raise err("ERR_INVALID_STATE",
                  f"Cannot end maintenance from status {v.get('status')}")
    v["status"] = "ACTIVE"
    v["maintenance_window_start"] = None
    v["maintenance_window_end"] = None
    db.stamp_update(v)
    return success(_serialize(v))
