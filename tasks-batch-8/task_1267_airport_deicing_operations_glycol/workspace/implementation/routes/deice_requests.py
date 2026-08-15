"""DeiceRequest routes: create, get, list, assign, defer, requeue, abort."""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import calc, derived

bp = Blueprint("deice_requests", __name__)

SIZE_CLASSES = {"SMALL", "MEDIUM", "LARGE"}
FLUID_TYPES = {"TYPE_I", "TYPE_IV"}
PRIORITIES = {"EMERGENCY", "SCHEDULED", "FLEXIBLE"}
OPERATION_TERMINAL_STATUSES = {"REWORK_REQUIRED", "CANCELLED", "VOIDED"}


def _get_request_or_404(rid):
    r = db.deice_requests.get(rid)
    if r is None:
        raise errors.not_found("request not found")
    return r


def _release_reservation_and_recompute(req):
    """Release fluid reservation of a request leaving the reserved set."""
    tank_id = req.get("assigned_tank_id")
    req["assigned_tank_id"] = None
    req["fluid_reservation_status"] = "UNRESERVED"
    if tank_id and tank_id in db.fluid_tanks:
        derived.recompute_tank_and_station(db.fluid_tanks[tank_id])
    else:
        derived.recompute_station_all(req["station_id"])


@bp.route("/deice-ops/deice-requests", methods=["POST"])
def create_request():
    user_id, role = middleware.require_roles("AirlineRep", "StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(
        payload,
        [
            "airline_id",
            "station_id",
            "flight_number",
            "aircraft_type",
            "size_class",
            "scheduled_departure",
            "fluid_type",
        ],
    )
    airline_id = payload["airline_id"]
    if role == "AirlineRep":
        middleware.require_own_airline(user_id, airline_id)
    airline = db.airlines.get(airline_id)
    if airline is None:
        raise errors.not_found("airline not found")
    station = db.stations.get(payload["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    flight_number = payload["flight_number"]
    if not isinstance(flight_number, str) or not flight_number:
        raise errors.invalid_request("flight_number must be a non-empty string")
    aircraft_type = payload["aircraft_type"]
    if not isinstance(aircraft_type, str) or not aircraft_type:
        raise errors.invalid_request("aircraft_type must be a non-empty string")
    size_class = util.require_enum(payload["size_class"], SIZE_CLASSES, "size_class")
    departure_dt = util.parse_iso(payload["scheduled_departure"], "scheduled_departure")
    fluid_type = util.require_enum(payload["fluid_type"], FLUID_TYPES, "fluid_type")
    priority = payload.get("priority", "SCHEDULED")
    priority = util.require_enum(priority, PRIORITIES, "priority")
    estimated_liters = calc.SIZE_TO_ESTIMATED[size_class]
    # Fiscal gate: outstanding + estimated_liters * base RATE > credit_limit
    base_rate = calc.RATE[fluid_type]
    estimated_charge = Decimal(estimated_liters) * Decimal(base_rate)
    exposure = Decimal(airline["outstanding_balance_cents"]) + estimated_charge
    if exposure > Decimal(airline["credit_limit_cents"]):
        raise errors.credit_limit_exceeded()
    # Tank reservation.
    chosen = calc.select_tank(station["id"], fluid_type, estimated_liters)
    now = util.iso_now()
    req = {
        "id": util.new_id(),
        "airline_id": airline["id"],
        "station_id": station["id"],
        "flight_number": flight_number,
        "aircraft_type": aircraft_type,
        "size_class": size_class,
        "scheduled_departure": payload["scheduled_departure"],
        "fluid_type": fluid_type,
        "priority": priority,
        "estimated_liters": estimated_liters,
        "assigned_tank_id": chosen["id"] if chosen else None,
        "fluid_reservation_status": "RESERVED" if chosen else "UNRESERVED",
        "assigned_pad_id": None,
        "epochs_in_queue": 0,
        "defer_count": 0,
        "status": "QUEUED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    req["_created_dt"] = db.get_clock()
    req["_departure_dt"] = departure_dt
    db.deice_requests[req["id"]] = req
    if chosen is not None:
        derived.recompute_tank_and_station(chosen)
    else:
        derived.recompute_station_all(station["id"])
    return response.success_object(serializers.deice_request(req), 201)


@bp.route("/deice-ops/deice-requests/<rid>", methods=["GET"])
def get_request(rid):
    user_id, role = middleware.require_roles("StationAdmin", "PadOperator", "AirlineRep")
    req = _get_request_or_404(rid)
    if role == "AirlineRep":
        middleware.require_own_airline(user_id, req["airline_id"])
    return response.success_object(serializers.deice_request(req), 200)


@bp.route("/deice-ops/deice-requests", methods=["GET"])
def list_requests():
    user_id, role = middleware.require_roles("StationAdmin", "PadOperator", "AirlineRep")
    limit, offset = util.get_pagination()
    airline_id = request.args.get("airline_id")
    station_id = request.args.get("station_id")
    assigned_tank_id = request.args.get("assigned_tank_id")
    assigned_pad_id = request.args.get("assigned_pad_id")
    status = request.args.get("status")
    items = list(db.deice_requests.values())
    if role == "AirlineRep":
        items = [r for r in items if r["airline_id"] == user_id]
    if airline_id is not None:
        items = [r for r in items if r["airline_id"] == airline_id]
    if station_id is not None:
        items = [r for r in items if r["station_id"] == station_id]
    if assigned_tank_id is not None:
        items = [r for r in items if r.get("assigned_tank_id") == assigned_tank_id]
    if assigned_pad_id is not None:
        items = [r for r in items if r.get("assigned_pad_id") == assigned_pad_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.deice_request(r) for r in page], limit, offset, total)


@bp.route("/deice-ops/deice-requests/<rid>/assign", methods=["POST"])
def assign_request(rid):
    middleware.require_roles("PadOperator")
    req = _get_request_or_404(rid)
    # State gate first: only QUEUED can be assigned.
    if req["status"] != "QUEUED":
        raise errors.invalid_state("request must be QUEUED to assign")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["pad_id", "window_start", "window_end"])
    pad = db.pads.get(payload["pad_id"])
    if pad is None:
        raise errors.not_found("pad not found")
    # Posture gates.
    station = db.stations.get(req["station_id"])
    derived.recompute_station_all(req["station_id"])
    if station["posture"] == "PERMIT_SUSPENDED":
        raise errors.permit_suspended()
    if station["posture"] == "FLUID_CONSTRAINED":
        raise errors.fluid_constrained()
    # Pad checks.
    if pad["station_id"] != req["station_id"]:
        raise errors.pad_not_available("pad is not at the request's station")
    if pad["status"] != "AVAILABLE":
        raise errors.pad_not_available()
    if calc.SIZE_ORDER[pad["max_size_class"]] < calc.SIZE_ORDER[req["size_class"]]:
        raise errors.pad_incompatible()
    # Reservation gate.
    if req["fluid_reservation_status"] != "RESERVED":
        raise errors.fluid_constrained("request is UNRESERVED at assign time")
    # Window well-formedness.
    window_start_dt = util.parse_iso(payload["window_start"], "window_start")
    window_end_dt = util.parse_iso(payload["window_end"], "window_end")
    if not (window_end_dt > window_start_dt):
        raise errors.invalid_request("window_end must be later than window_start")
    # Half-open overlap with non-terminal operations on this pad.
    for op in db.deice_operations.values():
        if op["pad_id"] != pad["id"]:
            continue
        if op["status"] in OPERATION_TERMINAL_STATUSES:
            continue
        if op.get("_window_start_dt") is None or op.get("_window_end_dt") is None:
            continue
        if window_start_dt < op["_window_end_dt"] and op["_window_start_dt"] < window_end_dt:
            raise errors.pad_window_overlap()
    # Success: request -> ASSIGNED, create PLANNED operation.
    now = util.iso_now()
    req["status"] = "ASSIGNED"
    req["assigned_pad_id"] = pad["id"]
    req["version"] += 1
    req["updated_at"] = now
    operation = {
        "id": util.new_id(),
        "request_id": req["id"],
        "station_id": req["station_id"],
        "pad_id": pad["id"],
        "tank_id": req.get("assigned_tank_id"),
        "parent_operation_id": None,
        "window_start": payload["window_start"],
        "window_end": payload["window_end"],
        "oat_celsius": None,
        "estimated_liters": req["estimated_liters"],
        "actual_liters": None,
        "collected_liters": None,
        "collection_pct": None,
        "collection_flag": None,
        "holdover_minutes": None,
        "holdover_variant": None,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    operation["_created_dt"] = db.get_clock()
    operation["_window_start_dt"] = window_start_dt
    operation["_window_end_dt"] = window_end_dt
    operation["_storm_surcharge_applies"] = False
    db.deice_operations[operation["id"]] = operation
    derived.recompute_station_all(req["station_id"])
    return response.success_object(serializers.deice_request(req), 200)


@bp.route("/deice-ops/deice-requests/<rid>/defer", methods=["POST"])
def defer_request(rid):
    middleware.require_roles("PadOperator")
    req = _get_request_or_404(rid)
    if req["status"] != "QUEUED":
        raise errors.invalid_state("request must be QUEUED to defer")
    req["status"] = "DEFERRED"
    req["defer_count"] = req.get("defer_count", 0) + 1
    req["version"] += 1
    req["updated_at"] = util.iso_now()
    return response.success_object(serializers.deice_request(req), 200)


@bp.route("/deice-ops/deice-requests/<rid>/requeue", methods=["POST"])
def requeue_request(rid):
    middleware.require_roles("PadOperator")
    req = _get_request_or_404(rid)
    if req["status"] != "DEFERRED":
        raise errors.invalid_state("request must be DEFERRED to requeue")
    req["status"] = "QUEUED"
    req["version"] += 1
    req["updated_at"] = util.iso_now()
    return response.success_object(serializers.deice_request(req), 200)


@bp.route("/deice-ops/deice-requests/<rid>/abort", methods=["POST"])
def abort_request(rid):
    user_id, role = middleware.require_roles("PadOperator", "AirlineRep")
    req = _get_request_or_404(rid)
    if role == "AirlineRep":
        middleware.require_own_airline(user_id, req["airline_id"])
    if req["status"] not in ("QUEUED", "ASSIGNED", "DEFERRED"):
        raise errors.invalid_state("request must be QUEUED, ASSIGNED, or DEFERRED to abort")
    if req["status"] == "ASSIGNED":
        # Cancel its PLANNED operation.
        for op in db.deice_operations.values():
            if op["request_id"] == req["id"] and op["status"] == "PLANNED":
                op["status"] = "CANCELLED"
                op["version"] += 1
                op["updated_at"] = util.iso_now()
    req["status"] = "ABORTED"
    req["version"] += 1
    req["updated_at"] = util.iso_now()
    _release_reservation_and_recompute(req)
    return response.success_object(serializers.deice_request(req), 200)
