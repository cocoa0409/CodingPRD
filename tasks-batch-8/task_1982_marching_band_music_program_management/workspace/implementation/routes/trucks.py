"""TruckCharter + TruckLoad endpoints."""
from datetime import timedelta
from flask import Blueprint, request
from db import store, new_id, now, now_iso, parse_dt
from errors import (
    raise_err, ERR_TRUCK_CHARTER_NOT_FOUND, ERR_TRUCK_LOAD_NOT_FOUND,
    ERR_INSTRUMENT_NOT_FOUND, ERR_EVENT_NOT_FOUND,
    ERR_VEHICLE_WINDOW_CONFLICT, ERR_CHARTER_NOT_LOADABLE, ERR_CHARTER_EMPTY,
    ERR_TRUCK_OVERWEIGHT, ERR_TRUCK_OVERVOLUME, ERR_LOAD_INSTRUMENT_INVALID,
    ERR_EVENT_WINDOW_INVALID, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import truck_charter_out, truck_load_out
from services.validators import body, require, check_unknown, to_int, to_str
from services.clock_eval import apply_time_transitions
from routes.programs import _get_program_or_404, _program_posture_open

bp = Blueprint("trucks", __name__)

LOADING_BUFFER_SECONDS = 7200


def _get_charter_or_404(cid):
    c = store.truck_charters.get(cid)
    if c is None:
        raise_err(ERR_TRUCK_CHARTER_NOT_FOUND, f"truck charter {cid} not found")
    return c


def _get_load_or_404(lid):
    l = store.truck_loads.get(lid)
    if l is None:
        raise_err(ERR_TRUCK_LOAD_NOT_FOUND, f"truck load {lid} not found")
    return l


def _vehicle_window_conflict(program_id, vehicle_label, window_start, window_end, exclude_id=None):
    """Buffered overlap check: ±2h on both ends of existing reservations."""
    buffer = timedelta(seconds=LOADING_BUFFER_SECONDS)
    for c in store.truck_charters.values():
        if c["id"] == exclude_id:
            continue
        if c["program_id"] != program_id:
            continue
        if c["vehicle_label"] != vehicle_label:
            continue
        if c["status"] not in ("RESERVED", "LOADED", "DEPARTED"):
            continue
        if window_start < (c["window_end"] + buffer) and (c["window_start"] - buffer) < window_end:
            return True
    return False


@bp.route("/band/truck-charters", methods=["POST"])
def create_charter():
    require_roles(["EquipmentManager"])
    data = body()
    check_unknown(data, {"program_id", "vehicle_label", "capacity_weight_lb",
                         "capacity_volume_cuft", "window_start", "window_end", "event_id"})
    require(data, "program_id", "vehicle_label", "capacity_weight_lb",
            "capacity_volume_cuft", "window_start", "window_end")
    pid = to_str(data["program_id"], "program_id")
    vehicle_label = to_str(data["vehicle_label"], "vehicle_label")
    capacity_weight_lb = to_int(data["capacity_weight_lb"], "capacity_weight_lb")
    capacity_volume_cuft = to_int(data["capacity_volume_cuft"], "capacity_volume_cuft")
    try:
        window_start = parse_dt(data["window_start"])
        window_end = parse_dt(data["window_end"])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "window_start/window_end must be ISO8601")
    event_id = data.get("event_id")

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    # Event FK check
    if event_id is not None:
        event_id = to_str(event_id, "event_id")
        if event_id not in store.events:
            raise_err(ERR_EVENT_NOT_FOUND, f"event {event_id} not found")

    # Window sanity
    if window_end <= window_start:
        raise_err(ERR_EVENT_WINDOW_INVALID, "window_end must be strictly after window_start")

    # Buffered overlap check
    if _vehicle_window_conflict(pid, vehicle_label, window_start, window_end):
        raise_err(ERR_VEHICLE_WINDOW_CONFLICT, "buffered vehicle window conflict")

    cid = new_id()
    now_s = now_iso()
    c = {
        "id": cid,
        "program_id": pid,
        "event_id": event_id,
        "vehicle_label": vehicle_label,
        "status": "RESERVED",
        "capacity_weight_lb": capacity_weight_lb,
        "capacity_volume_cuft": capacity_volume_cuft,
        "window_start": window_start,
        "window_end": window_end,
        "loaded_weight_lb": 0,
        "loaded_volume_cuft": 0,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.truck_charters[cid] = c
    return success(truck_charter_out(c), status=201)


@bp.route("/band/truck-charters", methods=["GET"])
def list_charters():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.truck_charters.values())
    pid = request.args.get("program_id")
    if pid:
        items = [c for c in items if c["program_id"] == pid]
    eid = request.args.get("event_id")
    if eid:
        items = [c for c in items if c.get("event_id") == eid]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    vl = request.args.get("vehicle_label")
    if vl:
        items = [c for c in items if c["vehicle_label"] == vl]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([truck_charter_out(c) for c in page], is_list=True, pagination=pag)


@bp.route("/band/truck-charters/<cid>", methods=["GET"])
def get_charter(cid):
    require_roles(["Any"])
    apply_time_transitions()
    c = _get_charter_or_404(cid)
    return success(truck_charter_out(c))


@bp.route("/band/truck-charters/<cid>/loads", methods=["POST"])
def add_load(cid):
    require_roles(["EquipmentManager"])
    c = _get_charter_or_404(cid)
    data = body()
    check_unknown(data, {"description", "weight_lb", "volume_cuft", "instrument_id"})
    require(data, "description", "weight_lb", "volume_cuft")
    description = to_str(data["description"], "description")
    weight_lb = to_int(data["weight_lb"], "weight_lb")
    volume_cuft = to_int(data["volume_cuft"], "volume_cuft")
    instrument_id = data.get("instrument_id")

    if weight_lb <= 0 or volume_cuft <= 0:
        raise_err(ERR_INVALID_REQUEST, "weight_lb and volume_cuft must be positive")

    # Charter must be loadable
    if c["status"] not in ("RESERVED", "LOADED"):
        raise_err(ERR_CHARTER_NOT_LOADABLE, "charter is not loadable")

    # Instrument FK + state
    if instrument_id is not None:
        instrument_id = to_str(instrument_id, "instrument_id")
        instr = store.instruments.get(instrument_id)
        if instr is None:
            raise_err(ERR_INSTRUMENT_NOT_FOUND, f"instrument {instrument_id} not found")
        if instr["status"] in ("RETIRED", "IN_MAINTENANCE"):
            raise_err(ERR_LOAD_INSTRUMENT_INVALID,
                      "loaded instrument must not be RETIRED or IN_MAINTENANCE")

    # Capacity check, weight before volume
    new_weight = c["loaded_weight_lb"] + weight_lb
    new_volume = c["loaded_volume_cuft"] + volume_cuft
    if new_weight > c["capacity_weight_lb"]:
        raise_err(ERR_TRUCK_OVERWEIGHT, "truck capacity exceeded (weight)")
    if new_volume > c["capacity_volume_cuft"]:
        raise_err(ERR_TRUCK_OVERVOLUME, "truck capacity exceeded (volume)")

    lid = new_id()
    now_s = now_iso()
    l = {
        "id": lid,
        "charter_id": cid,
        "instrument_id": instrument_id,
        "description": description,
        "weight_lb": weight_lb,
        "volume_cuft": volume_cuft,
        "created_at": now_s,
    }
    store.truck_loads[lid] = l
    # Update charter
    c["loaded_weight_lb"] = new_weight
    c["loaded_volume_cuft"] = new_volume
    if c["status"] == "RESERVED":
        c["status"] = "LOADED"
    c["version"] += 1
    c["updated_at"] = now_s
    return success(truck_load_out(l), status=201)


@bp.route("/band/truck-loads", methods=["GET"])
def list_loads():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.truck_loads.values())
    cid = request.args.get("charter_id")
    if cid:
        items = [l for l in items if l["charter_id"] == cid]
    iid = request.args.get("instrument_id")
    if iid:
        items = [l for l in items if l.get("instrument_id") == iid]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([truck_load_out(l) for l in page], is_list=True, pagination=pag)


@bp.route("/band/truck-loads/<lid>", methods=["GET"])
def get_load(lid):
    require_roles(["Any"])
    apply_time_transitions()
    l = _get_load_or_404(lid)
    return success(truck_load_out(l))


@bp.route("/band/truck-charters/<cid>/depart", methods=["POST"])
def depart_charter(cid):
    require_roles(["EquipmentManager"])
    c = _get_charter_or_404(cid)
    if c["status"] != "LOADED":
        raise_err(ERR_CHARTER_NOT_LOADABLE, "charter is not LOADED")
    if c["loaded_weight_lb"] < 1:
        raise_err(ERR_CHARTER_EMPTY, "charter has no load")
    c["status"] = "DEPARTED"
    c["version"] += 1
    c["updated_at"] = now_iso()
    return success(truck_charter_out(c))


@bp.route("/band/truck-charters/<cid>/return", methods=["POST"])
def return_charter(cid):
    require_roles(["EquipmentManager"])
    c = _get_charter_or_404(cid)
    if c["status"] != "DEPARTED":
        raise_err(ERR_INVALID_STATE, "charter is not DEPARTED")
    c["status"] = "RETURNED"
    c["version"] += 1
    c["updated_at"] = now_iso()
    return success(truck_charter_out(c))


@bp.route("/band/truck-charters/<cid>/cancel", methods=["POST"])
def cancel_charter(cid):
    require_roles(["EquipmentManager"])
    c = _get_charter_or_404(cid)
    if c["status"] not in ("RESERVED", "LOADED"):
        raise_err(ERR_INVALID_STATE, "charter cannot be cancelled from current state")
    c["status"] = "CANCELLED"
    c["version"] += 1
    c["updated_at"] = now_iso()
    return success(truck_charter_out(c))
