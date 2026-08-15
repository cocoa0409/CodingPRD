"""Fluid tank routes: create, get, list, replenish."""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import calc, derived

bp = Blueprint("fluid_tanks", __name__)

FLUID_TYPES = {"TYPE_I", "TYPE_IV"}
CONCENTRATIONS = {100, 75, 50}


@bp.route("/deice-ops/fluid-tanks", methods=["POST"])
def create_tank():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(
        payload,
        [
            "station_id",
            "fluid_type",
            "concentration_pct",
            "capacity_liters",
            "on_hand_liters",
            "reorder_threshold_liters",
        ],
    )
    station = db.stations.get(payload["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    fluid_type = util.require_enum(payload["fluid_type"], FLUID_TYPES, "fluid_type")
    concentration_pct = util.to_int(payload["concentration_pct"], "concentration_pct")
    if concentration_pct not in CONCENTRATIONS:
        raise errors.invalid_request("concentration_pct must be one of 100, 75, 50")
    capacity_liters = util.to_int(payload["capacity_liters"], "capacity_liters")
    if capacity_liters <= 0:
        raise errors.invalid_request("capacity_liters must be positive")
    on_hand_liters = float(util.to_decimal(payload["on_hand_liters"], "on_hand_liters"))
    if on_hand_liters < 0:
        raise errors.invalid_request("on_hand_liters must be >= 0")
    if Decimal(str(on_hand_liters)) > Decimal(str(capacity_liters)):
        raise errors.invalid_request("on_hand_liters cannot exceed capacity_liters")
    reorder_threshold_liters = util.to_int(payload["reorder_threshold_liters"], "reorder_threshold_liters")
    now = util.iso_now()
    tank = {
        "id": util.new_id(),
        "station_id": station["id"],
        "fluid_type": fluid_type,
        "concentration_pct": concentration_pct,
        "capacity_liters": capacity_liters,
        "on_hand_liters": on_hand_liters,
        "reserved_liters": 0,
        "available_liters": on_hand_liters,
        "reorder_threshold_liters": reorder_threshold_liters,
        "status": "OK",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    tank["_created_dt"] = db.get_clock()
    db.fluid_tanks[tank["id"]] = tank
    derived.recompute_tank_and_station(tank)
    return response.success_object(serializers.fluid_tank(tank), 201)


@bp.route("/deice-ops/fluid-tanks/<tid>", methods=["GET"])
def get_tank(tid):
    middleware.require_roles("StationAdmin", "PadOperator", "EnvironmentalOfficer")
    tank = db.fluid_tanks.get(tid)
    if tank is None:
        raise errors.not_found("tank not found")
    derived.recompute_tank(tank)
    return response.success_object(serializers.fluid_tank(tank), 200)


@bp.route("/deice-ops/fluid-tanks", methods=["GET"])
def list_tanks():
    middleware.require_roles("StationAdmin", "PadOperator", "EnvironmentalOfficer")
    limit, offset = util.get_pagination()
    station_id = request.args.get("station_id")
    fluid_type = request.args.get("fluid_type")
    status = request.args.get("status")
    items = list(db.fluid_tanks.values())
    for t in items:
        derived.recompute_tank(t)
    if station_id is not None:
        items = [t for t in items if t["station_id"] == station_id]
    if fluid_type is not None:
        items = [t for t in items if t["fluid_type"] == fluid_type]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda t: t["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.fluid_tank(t) for t in page], limit, offset, total)


@bp.route("/deice-ops/fluid-tanks/<tid>/replenish", methods=["POST"])
def replenish_tank(tid):
    middleware.require_roles("StationAdmin")
    tank = db.fluid_tanks.get(tid)
    if tank is None:
        raise errors.not_found("tank not found")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["liters"])
    liters = util.to_decimal(payload["liters"], "liters")
    if liters <= 0:
        raise errors.invalid_request("liters must be positive")
    new_on_hand = Decimal(str(tank["on_hand_liters"])) + liters
    if new_on_hand > Decimal(str(tank["capacity_liters"])):
        raise errors.tank_capacity_exceeded()
    tank["on_hand_liters"] = float(new_on_hand)
    tank["version"] += 1
    tank["updated_at"] = util.iso_now()
    derived.recompute_tank(tank)
    # Retry reservations for UNRESERVED requests of this station with matching
    # fluid_type, in queue order, while eligibility holds.
    pending = [
        r
        for r in db.deice_requests.values()
        if r["station_id"] == tank["station_id"]
        and r["fluid_reservation_status"] == "UNRESERVED"
        and r["fluid_type"] == tank["fluid_type"]
        and r["status"] in ("QUEUED", "DEFERRED")
    ]
    pending.sort(key=calc.queue_sort_key)
    for r in pending:
        chosen = calc.select_tank(r["station_id"], r["fluid_type"], r["estimated_liters"])
        if chosen is None:
            break
        r["assigned_tank_id"] = chosen["id"]
        r["fluid_reservation_status"] = "RESERVED"
        r["updated_at"] = util.iso_now()
        r["version"] += 1
        derived.recompute_tank(chosen)
    derived.recompute_station_all(tank["station_id"])
    # Refresh tank view after potential reservations consumed availability.
    tank = db.fluid_tanks[tid]
    return response.success_object(serializers.fluid_tank(tank), 200)
