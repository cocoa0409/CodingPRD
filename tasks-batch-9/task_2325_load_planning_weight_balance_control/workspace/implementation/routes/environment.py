"""Runways, performance bands and passenger weight programmes (PRD §3.1)."""
from flask import Blueprint

import db
import resolve
import response
import validate
from errors import ERR_DUPLICATE_KEY, fail
from middleware import ANY_ROLE, authorize

bp = Blueprint("environment", __name__)

PROGRAM_KINDS = ("STANDARD", "ACTUAL")


# ----------------------------------------------------------------- Runway
@bp.post("/runways")
@authorize("LoadControlAdmin")
def create_runway():
    payload = validate.body()
    row = {
        "airport_code": validate.req_str(payload, "airport_code"),
        "designator": validate.req_str(payload, "designator"),
        "elevation_ft": validate.req_num(payload, "elevation_ft"),
        "length_m": validate.req_num(payload, "length_m", ge=0),
        "slot_capacity_per_window": validate.opt_int(
            payload, "slot_capacity_per_window", default=2, ge=0
        ),
        "status": "OPEN",
    }
    duplicate = any(
        r["airport_code"] == row["airport_code"] and r["designator"] == row["designator"]
        for r in db.runways.values()
    )
    if duplicate:
        fail(ERR_DUPLICATE_KEY, "That designator already exists at the airport.")
    return response.object_response(db.public(db.insert(db.runways, row)), 201)


@bp.get("/runways/<row_id>")
@authorize(*ANY_ROLE)
def read_runway(row_id):
    return response.object_response(db.public(resolve.runway(row_id)))


@bp.post("/runways/<row_id>/close")
@authorize("LoadControlAdmin")
def close_runway(row_id):
    runway = resolve.runway(row_id)
    runway["status"] = "CLOSED"
    db.touch(runway)
    return response.object_response(db.public(runway))


# -------------------------------------------------------- PerformanceBand
@bp.post("/performance-bands")
@authorize("LoadControlAdmin")
def create_performance_band():
    payload = validate.body()
    row = {
        "runway_id": validate.req_str(payload, "runway_id"),
        "aircraft_type_code": validate.req_str(payload, "aircraft_type_code"),
        "temp_lo_c": validate.req_num(payload, "temp_lo_c"),
        "temp_hi_c": validate.req_num(payload, "temp_hi_c"),
        "base_limit_weight_kg": validate.req_num(payload, "base_limit_weight_kg", ge=0),
    }
    resolve.runway(row["runway_id"])
    return response.object_response(db.public(db.insert(db.performance_bands, row)), 201)


@bp.get("/performance-bands/<row_id>")
@authorize(*ANY_ROLE)
def read_performance_band(row_id):
    return response.object_response(db.public(resolve.performance_band(row_id)))


@bp.get("/runways/<row_id>/performance-bands")
@authorize(*ANY_ROLE)
def list_runway_performance_bands(row_id):
    validate.pagination()
    type_code = validate.query_str("aircraft_type_code")
    resolve.runway(row_id)
    rows = db.ordered(
        [
            b
            for b in db.performance_bands.values()
            if b["runway_id"] == row_id
            and (type_code is None or b["aircraft_type_code"] == type_code)
        ]
    )
    items, meta = validate.paginate(rows)
    return response.list_response(items, meta)


# ----------------------------------------------------------- WeightProgram
@bp.post("/weight-programs")
@authorize("LoadControlAdmin")
def create_weight_program():
    payload = validate.body()
    row = {
        "code": validate.req_str(payload, "code"),
        "program_kind": validate.req_enum(payload, "program_kind", PROGRAM_KINDS),
        "male_kg": validate.req_num(payload, "male_kg", ge=0),
        "female_kg": validate.req_num(payload, "female_kg", ge=0),
        "child_kg": validate.req_num(payload, "child_kg", ge=0),
        "infant_kg": validate.req_num(payload, "infant_kg", ge=0),
        "checked_bag_kg": validate.req_num(payload, "checked_bag_kg", ge=0),
        "documentation_ref": validate.req_str(payload, "documentation_ref"),
        "status": "ACTIVE",
    }
    if any(p["code"] == row["code"] for p in db.weight_programs.values()):
        fail(ERR_DUPLICATE_KEY, "That weight programme code already exists.")
    return response.object_response(db.public(db.insert(db.weight_programs, row)), 201)


@bp.get("/weight-programs/<row_id>")
@authorize(*ANY_ROLE)
def read_weight_program(row_id):
    return response.object_response(db.public(resolve.weight_program(row_id)))


@bp.post("/weight-programs/<row_id>/withdraw")
@authorize("LoadControlAdmin")
def withdraw_weight_program(row_id):
    program = resolve.weight_program(row_id)
    program["status"] = "WITHDRAWN"
    db.touch(program)
    return response.object_response(db.public(program))
