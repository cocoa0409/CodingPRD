"""Tails: registration and the read-only rotation view."""
from flask import Blueprint

import derive
import reqval as rv
from db import store
from middleware import authenticate
from response import ok, raw, written
from routes.common import READ_ROLES, list_response, read_one, require_carrier_active

bp = Blueprint("aircraft", __name__)


@bp.post("/aircraft")
def create_aircraft():
    authenticate(("NetworkPlanner",))
    payload = rv.body()
    carrier_id = rv.req_str(payload, "carrier_id", 1)
    base_station_id = rv.req_str(payload, "base_station_id", 1)
    registration = rv.req_str(payload, "registration", 4, 8)
    fleet_type = rv.req_str(payload, "fleet_type_code", 3, 4, r"[A-Z0-9]{3,4}")
    seats = rv.req_int(payload, "seats", 1)
    min_turn = rv.req_int(payload, "min_turn_minutes", 0)
    max_block = rv.req_int(payload, "max_daily_block_minutes", 1)
    required_check = rv.req_int(payload, "required_check_minutes", 0)
    check_required = rv.opt_bool(payload, "maintenance_check_required", False)
    status = rv.opt_enum(payload, "status", "aircraft_status", "IN_SERVICE")
    for row in store.values("aircraft"):
        if row["registration"] == registration:
            rv.bad("A tail with that registration already exists.")
    carrier = store.require("carriers", carrier_id)
    store.require("stations", base_station_id)
    require_carrier_active(carrier)
    row = store.insert("aircraft", {
        "carrier_id": carrier_id,
        "base_station_id": base_station_id,
        "registration": registration,
        "fleet_type_code": fleet_type,
        "seats": seats,
        "min_turn_minutes": min_turn,
        "max_daily_block_minutes": max_block,
        "required_check_minutes": required_check,
        "maintenance_check_required": check_required,
        "status": status,
        "assigned_leg_count": 0,
        "maintenance_opportunity_minutes": 0,
        "cumulative_ground_minutes": 0,
        "rotation_feasibility_status": "UNCHECKED",
    })
    return written(row, 201)


@bp.get("/aircraft/<aircraft_id>")
def get_aircraft(aircraft_id):
    return ok(read_one("aircraft", aircraft_id))


@bp.get("/aircraft")
def list_aircraft():
    authenticate(READ_ROLES)
    return list_response("aircraft", [
        ("carrier_id", rv.q_str("carrier_id")),
        ("base_station_id", rv.q_str("base_station_id")),
        ("status", rv.q_enum("status", "aircraft_status")),
        ("fleet_type_code", rv.q_str("fleet_type_code")),
        ("rotation_feasibility_status", rv.q_enum("rotation_feasibility_status", "rotation_feasibility_status")),
    ])


@bp.get("/aircraft/<aircraft_id>/rotation-feasibility")
def rotation_feasibility(aircraft_id):
    aircraft = read_one("aircraft", aircraft_id)
    return raw(derive.rotation_view(aircraft))
