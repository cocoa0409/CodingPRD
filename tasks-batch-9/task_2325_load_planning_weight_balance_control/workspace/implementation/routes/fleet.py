"""Airframes and their compartments (PRD §3.1)."""
from flask import Blueprint

import db
import resolve
import response
import validate
from errors import ERR_DUPLICATE_KEY, ERR_INVALID_REQUEST, fail
from middleware import ANY_ROLE, authorize

bp = Blueprint("fleet", __name__)

AIRCRAFT_STATUSES = ("IN_SERVICE", "GROUNDED")
COMPARTMENT_KINDS = ("CABIN_ZONE", "HOLD")

_NON_NEGATIVE = (
    "max_takeoff_weight_kg",
    "max_landing_weight_kg",
    "max_zero_fuel_weight_kg",
    "max_taxi_weight_kg",
    "mac_length_m",
    "tow_knee_weight_kg",
)
_UNBOUNDED = (
    "basic_index",
    "ref_arm_m",
    "lemac_m",
    "index_c",
    "index_k",
    "fuel_arm_m",
    "zfw_fwd_limit_pct_mac",
    "zfw_aft_limit_pct_mac",
    "tow_fwd_limit_pct_mac",
    "tow_aft_limit_pct_mac",
)


# --------------------------------------------------------------- Aircraft
@bp.post("/aircraft")
@authorize("LoadControlAdmin")
def create_aircraft():
    payload = validate.body()
    row = {
        "registration": validate.req_str(payload, "registration"),
        "type_code": validate.req_str(payload, "type_code"),
        "basic_empty_weight_kg": validate.req_num(payload, "basic_empty_weight_kg", gt=0),
        "seat_count": validate.req_int(payload, "seat_count", ge=0),
    }
    for name in _NON_NEGATIVE:
        row[name] = validate.req_num(payload, name, ge=0)
    for name in _UNBOUNDED:
        row[name] = validate.req_num(payload, name)
    knee = validate.req_num(payload, "tow_aft_knee_adjust_pct_mac")
    if knee > 0:
        fail(ERR_INVALID_REQUEST, "Field 'tow_aft_knee_adjust_pct_mac' must not be positive.")
    row["tow_aft_knee_adjust_pct_mac"] = knee
    row["status"] = "IN_SERVICE"

    if any(a["registration"] == row["registration"] for a in db.aircraft.values()):
        fail(ERR_DUPLICATE_KEY, "That registration is already recorded.")
    return response.object_response(db.public(db.insert(db.aircraft, row)), 201)


@bp.get("/aircraft/<row_id>")
@authorize(*ANY_ROLE)
def read_aircraft(row_id):
    return response.object_response(db.public(resolve.aircraft(row_id)))


@bp.get("/aircraft")
@authorize(*ANY_ROLE)
def list_aircraft():
    status = validate.query_enum("status", AIRCRAFT_STATUSES)
    rows = db.ordered(
        [a for a in db.aircraft.values() if status is None or a["status"] == status]
    )
    items, meta = validate.paginate(rows)
    return response.list_response(items, meta)


@bp.post("/aircraft/<row_id>/ground")
@authorize("LoadControlAdmin")
def ground_aircraft(row_id):
    airframe = resolve.aircraft(row_id)
    airframe["status"] = "GROUNDED"
    db.touch(airframe)
    return response.object_response(db.public(airframe))


# ------------------------------------------------------------ Compartment
@bp.post("/compartments")
@authorize("LoadControlAdmin")
def create_compartment():
    payload = validate.body()
    row = {
        "aircraft_id": validate.req_str(payload, "aircraft_id"),
        "code": validate.req_str(payload, "code"),
        "kind": validate.req_enum(payload, "kind", COMPARTMENT_KINDS),
        "arm_m": validate.req_num(payload, "arm_m"),
        "max_weight_kg": validate.req_num(payload, "max_weight_kg", ge=0),
        "running_load_limit_kg_per_m": validate.req_num(
            payload, "running_load_limit_kg_per_m", ge=0
        ),
        "length_m": validate.req_num(payload, "length_m", gt=0),
        "seat_capacity": validate.opt_int(payload, "seat_capacity", default=0, ge=0),
    }
    resolve.aircraft(row["aircraft_id"])
    duplicate = any(
        c["aircraft_id"] == row["aircraft_id"] and c["code"] == row["code"]
        for c in db.compartments.values()
    )
    if duplicate:
        fail(ERR_DUPLICATE_KEY, "That compartment code already exists on the airframe.")
    return response.object_response(db.public(db.insert(db.compartments, row)), 201)


@bp.get("/compartments/<row_id>")
@authorize(*ANY_ROLE)
def read_compartment(row_id):
    return response.object_response(db.public(resolve.compartment(row_id)))


@bp.get("/aircraft/<row_id>/compartments")
@authorize(*ANY_ROLE)
def list_aircraft_compartments(row_id):
    validate.pagination()
    kind = validate.query_enum("kind", COMPARTMENT_KINDS)
    resolve.aircraft(row_id)
    rows = db.ordered(
        [
            c
            for c in db.compartments.values()
            if c["aircraft_id"] == row_id and (kind is None or c["kind"] == kind)
        ]
    )
    items, meta = validate.paginate(rows)
    return response.list_response(items, meta)
