"""Cabin-zone seating lines and hold bag allocations (PRD §3.3)."""
from flask import Blueprint

import calc
import db
import resolve
import response
import validate
from calc import D
from errors import (
    ERR_ACTUAL_WEIGHT_NOT_PERMITTED,
    ERR_ACTUAL_WEIGHT_REQUIRED,
    ERR_COMPARTMENT_KIND_MISMATCH,
    ERR_COMPARTMENT_NOT_ON_AIRCRAFT,
    ERR_DUPLICATE_KEY,
    ERR_FLIGHT_INVALID_STATE,
    ERR_PLAN_INVALID_STATE,
    ERR_SEAT_CAPACITY_EXCEEDED,
    fail,
)
from middleware import ANY_ROLE, authorize
from services import balance

bp = Blueprint("distribution", __name__)

WRITABLE_PLAN_STATUSES = ("DRAFT", "COMPUTED")


def _writable_plan(plan):
    if plan["status"] not in WRITABLE_PLAN_STATUSES or balance.sheets_freeze_plan(plan["id"]):
        fail(ERR_PLAN_INVALID_STATE)


# --------------------------------------------------------------- pax lines
@bp.post("/pax-lines")
@authorize("LoadController")
def create_pax_line():
    payload = validate.body()
    row = {
        "load_plan_id": validate.req_str(payload, "load_plan_id"),
        "compartment_id": validate.req_str(payload, "compartment_id"),
        "male_count": validate.opt_int(payload, "male_count", default=0, ge=0),
        "female_count": validate.opt_int(payload, "female_count", default=0, ge=0),
        "child_count": validate.opt_int(payload, "child_count", default=0, ge=0),
        "infant_count": validate.opt_int(payload, "infant_count", default=0, ge=0),
        "actual_weight_kg": validate.opt_num(payload, "actual_weight_kg", ge=0),
    }
    supplied_actual = validate.has(payload, "actual_weight_kg")

    plan = resolve.load_plan(row["load_plan_id"])
    compartment = resolve.compartment(row["compartment_id"])
    flight, aircraft, program = balance.plan_context(plan)

    duplicate = any(
        line["load_plan_id"] == row["load_plan_id"]
        and line["compartment_id"] == row["compartment_id"]
        for line in db.pax_lines.values()
    )
    if duplicate:
        fail(ERR_DUPLICATE_KEY, "That cabin zone is already seated on this plan.")
    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_FLIGHT_INVALID_STATE)
    _writable_plan(plan)
    if compartment["aircraft_id"] != flight["aircraft_id"]:
        fail(ERR_COMPARTMENT_NOT_ON_AIRCRAFT)
    if compartment["kind"] != "CABIN_ZONE":
        fail(ERR_COMPARTMENT_KIND_MISMATCH)

    if program["program_kind"] == "ACTUAL" and not supplied_actual:
        fail(ERR_ACTUAL_WEIGHT_REQUIRED)
    if program["program_kind"] == "STANDARD" and supplied_actual:
        fail(ERR_ACTUAL_WEIGHT_NOT_PERMITTED)

    seated = row["male_count"] + row["female_count"] + row["child_count"]
    if seated > int(compartment["seat_capacity"]):
        fail(ERR_SEAT_CAPACITY_EXCEEDED)

    weight = calc.pax_line_weight(row, program)
    row["line_weight_kg"] = float(weight)
    row["index_delta"] = float(
        calc.index_delta(weight, compartment["arm_m"], aircraft["ref_arm_m"], aircraft["index_c"])
    )

    line = db.insert(db.pax_lines, row)
    balance.invalidate_computation(flight, plan)
    return response.object_response(db.public(line), 201)


@bp.get("/pax-lines/<row_id>")
@authorize(*ANY_ROLE)
def read_pax_line(row_id):
    return response.object_response(db.public(resolve.pax_line(row_id)))


@bp.get("/pax-lines")
@authorize(*ANY_ROLE)
def list_pax_lines():
    validate.pagination()
    plan_id = validate.query_str("load_plan_id")
    compartment_id = validate.query_str("compartment_id")
    rows = [
        line
        for line in db.pax_lines.values()
        if (plan_id is None or line["load_plan_id"] == plan_id)
        and (compartment_id is None or line["compartment_id"] == compartment_id)
    ]
    items, meta = validate.paginate(db.ordered(rows))
    return response.list_response(items, meta)


@bp.delete("/pax-lines/<row_id>")
@authorize("LoadController")
def delete_pax_line(row_id):
    line = resolve.pax_line(row_id)
    plan = db.load_plans[line["load_plan_id"]]
    flight, _aircraft, _program = balance.plan_context(plan)
    _writable_plan(plan)
    del db.pax_lines[row_id]
    balance.invalidate_computation(flight, plan)
    return "", 204


# --------------------------------------------------------- bag allocations
@bp.post("/bag-allocations")
@authorize("LoadController", "RampAgent")
def create_bag_allocation():
    payload = validate.body()
    row = {
        "load_plan_id": validate.req_str(payload, "load_plan_id"),
        "compartment_id": validate.req_str(payload, "compartment_id"),
        "bag_count": validate.opt_int(payload, "bag_count", default=0, ge=0),
        "bag_weight_kg": validate.opt_num(payload, "bag_weight_kg", ge=0),
    }

    plan = resolve.load_plan(row["load_plan_id"])
    compartment = resolve.compartment(row["compartment_id"])
    flight, aircraft, program = balance.plan_context(plan)

    duplicate = any(
        allocation["load_plan_id"] == row["load_plan_id"]
        and allocation["compartment_id"] == row["compartment_id"]
        for allocation in db.bag_allocations.values()
    )
    if duplicate:
        fail(ERR_DUPLICATE_KEY, "That hold already has a bag allocation on this plan.")
    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_FLIGHT_INVALID_STATE)
    _writable_plan(plan)
    if compartment["aircraft_id"] != flight["aircraft_id"]:
        fail(ERR_COMPARTMENT_NOT_ON_AIRCRAFT)
    if compartment["kind"] != "HOLD":
        fail(ERR_COMPARTMENT_KIND_MISMATCH)

    weight = calc.bag_effective_weight(row, program)
    occupancy = balance.hold_occupancy(flight["id"], row["compartment_id"])
    balance.check_hold_ceilings(compartment, occupancy + D(weight))

    row["effective_weight_kg"] = float(weight)
    row["index_delta"] = float(
        calc.index_delta(weight, compartment["arm_m"], aircraft["ref_arm_m"], aircraft["index_c"])
    )
    allocation = db.insert(db.bag_allocations, row)
    balance.invalidate_computation(flight, plan)
    return response.object_response(db.public(allocation), 201)


@bp.get("/bag-allocations/<row_id>")
@authorize(*ANY_ROLE)
def read_bag_allocation(row_id):
    return response.object_response(db.public(resolve.bag_allocation(row_id)))


@bp.get("/bag-allocations")
@authorize(*ANY_ROLE)
def list_bag_allocations():
    validate.pagination()
    plan_id = validate.query_str("load_plan_id")
    compartment_id = validate.query_str("compartment_id")
    rows = [
        allocation
        for allocation in db.bag_allocations.values()
        if (plan_id is None or allocation["load_plan_id"] == plan_id)
        and (compartment_id is None or allocation["compartment_id"] == compartment_id)
    ]
    items, meta = validate.paginate(db.ordered(rows))
    return response.list_response(items, meta)
