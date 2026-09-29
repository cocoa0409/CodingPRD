"""Flight creation, condition revision and lifecycle (PRD §3.2, §3.7)."""
from flask import Blueprint

import calc
import clock
import db
import resolve
import response
import validate
from errors import (
    ERR_AIRCRAFT_GROUNDED,
    ERR_AIRCRAFT_OCCUPANCY_CONFLICT,
    ERR_FLIGHT_INVALID_STATE,
    ERR_FUEL_FIGURES_INCONSISTENT,
    ERR_INVALID_INTERVAL,
    ERR_INVALID_REQUEST,
    ERR_LOAD_NOT_RELEASED,
    ERR_NO_PERFORMANCE_BAND,
    ERR_RUNWAY_CLOSED,
    ERR_RUNWAY_SLOT_FULL,
    ERR_WEIGHT_PROGRAM_WITHDRAWN,
    fail,
)
from middleware import ANY_ROLE, authorize

bp = Blueprint("flights", __name__)

FLIGHT_STATUSES = ("PLANNING", "LOAD_CONTROLLED", "DEPARTED", "CLOSED", "CANCELLED")
RUNWAY_CONDITIONS = ("DRY", "WET", "CONTAMINATED")
OCCUPYING_STATUSES = ("PLANNING", "LOAD_CONTROLLED", "DEPARTED")


# ------------------------------------------------------------- derivations
def select_band(flight, aircraft):
    matches = [
        band
        for band in db.ordered(list(db.performance_bands.values()))
        if band["runway_id"] == flight["departure_runway_id"]
        and band["aircraft_type_code"] == aircraft["type_code"]
        and calc.D(band["temp_lo_c"])
        <= calc.D(flight["outside_air_temp_c"])
        < calc.D(band["temp_hi_c"])
    ]
    if not matches:
        fail(ERR_NO_PERFORMANCE_BAND)
    return matches[0]


def check_fuel(ramp, taxi, trip):
    if calc.D(taxi) > calc.D(ramp):
        fail(ERR_FUEL_FIGURES_INCONSISTENT)
    if calc.D(trip) > calc.D(ramp) - calc.D(taxi):
        fail(ERR_FUEL_FIGURES_INCONSISTENT)


def derive_figures(flight, aircraft, runway, band):
    dow, doi = calc.dry_operating(aircraft, flight["crew_weight_kg"], flight["crew_arm_m"])
    perf = calc.performance_limited_takeoff_weight(
        band,
        runway,
        flight["outside_air_temp_c"],
        flight["headwind_component_kt"],
        flight["runway_condition"],
    )
    payload, limiting = calc.allowed_payload(
        aircraft,
        dow,
        perf,
        flight["ramp_fuel_kg"],
        flight["taxi_fuel_kg"],
        flight["trip_fuel_kg"],
    )
    flight["dry_operating_weight_kg"] = float(dow)
    flight["dry_operating_index"] = float(doi)
    flight["performance_limited_takeoff_weight_kg"] = float(perf)
    flight["allowed_payload_kg"] = float(payload)
    flight["limiting_factor"] = limiting


def _instant(payload, name):
    raw = validate.req_str(payload, name)
    parsed = clock.parse_iso(raw)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 instant." % name)
    return raw, parsed


# ------------------------------------------------------------------ create
@bp.post("/flights")
@authorize("LoadController", "LoadControlAdmin")
def create_flight():
    payload = validate.body()
    off_raw, off = _instant(payload, "scheduled_off_block_utc")
    on_raw, on = _instant(payload, "scheduled_on_block_utc")
    row = {
        "flight_number": validate.req_str(payload, "flight_number"),
        "aircraft_id": validate.req_str(payload, "aircraft_id"),
        "departure_runway_id": validate.req_str(payload, "departure_runway_id"),
        "weight_program_id": validate.req_str(payload, "weight_program_id"),
        "scheduled_off_block_utc": off_raw,
        "scheduled_on_block_utc": on_raw,
        "crew_weight_kg": validate.req_num(payload, "crew_weight_kg", ge=0),
        "crew_arm_m": validate.req_num(payload, "crew_arm_m"),
        "ramp_fuel_kg": validate.req_num(payload, "ramp_fuel_kg", ge=0),
        "taxi_fuel_kg": validate.req_num(payload, "taxi_fuel_kg", ge=0),
        "trip_fuel_kg": validate.req_num(payload, "trip_fuel_kg", ge=0),
        "outside_air_temp_c": validate.req_num(payload, "outside_air_temp_c"),
        "headwind_component_kt": validate.req_num(payload, "headwind_component_kt"),
        "runway_condition": validate.req_enum(payload, "runway_condition", RUNWAY_CONDITIONS),
        "status": "PLANNING",
        "load_release_state": "OPEN",
        "dg_hold_count": 0,
        "dry_operating_weight_kg": 0,
        "dry_operating_index": 0,
        "performance_limited_takeoff_weight_kg": 0,
        "allowed_payload_kg": 0,
        "limiting_factor": "PERFORMANCE",
        "_off": off,
        "_on": on,
    }

    aircraft = resolve.aircraft(row["aircraft_id"])
    runway = resolve.runway(row["departure_runway_id"])
    program = resolve.weight_program(row["weight_program_id"])

    if aircraft["status"] != "IN_SERVICE":
        fail(ERR_AIRCRAFT_GROUNDED)
    if runway["status"] != "OPEN":
        fail(ERR_RUNWAY_CLOSED)
    if program["status"] != "ACTIVE":
        fail(ERR_WEIGHT_PROGRAM_WITHDRAWN)

    band = select_band(row, aircraft)

    if not on > off:
        fail(ERR_INVALID_INTERVAL)

    new_start = off
    new_end = on + clock.TURNAROUND_BUFFER
    for other in db.flights.values():
        if other["aircraft_id"] != row["aircraft_id"]:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        other_start = other["_off"]
        other_end = other["_on"] + clock.TURNAROUND_BUFFER
        if new_start <= other_end and other_start <= new_end:
            fail(ERR_AIRCRAFT_OCCUPANCY_CONFLICT)

    window_start = clock.slot_window_start(off)
    window_end = window_start + clock.SLOT_WINDOW
    taken = 0
    for other in db.flights.values():
        if other["departure_runway_id"] != row["departure_runway_id"]:
            continue
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        if window_start <= other["_off"] < window_end:
            taken += 1
    if taken >= int(runway["slot_capacity_per_window"]):
        fail(ERR_RUNWAY_SLOT_FULL)

    check_fuel(row["ramp_fuel_kg"], row["taxi_fuel_kg"], row["trip_fuel_kg"])

    derive_figures(row, aircraft, runway, band)
    return response.object_response(db.public(db.insert(db.flights, row)), 201)


# -------------------------------------------------------------------- read
@bp.get("/flights/<row_id>")
@authorize(*ANY_ROLE)
def read_flight(row_id):
    return response.object_response(db.public(resolve.flight(row_id)))


@bp.get("/flights")
@authorize(*ANY_ROLE)
def list_flights():
    validate.pagination()
    aircraft_id = validate.query_str("aircraft_id")
    runway_id = validate.query_str("departure_runway_id")
    program_id = validate.query_str("weight_program_id")
    status = validate.query_enum("status", FLIGHT_STATUSES)
    rows = []
    for flight in db.flights.values():
        if aircraft_id is not None and flight["aircraft_id"] != aircraft_id:
            continue
        if runway_id is not None and flight["departure_runway_id"] != runway_id:
            continue
        if program_id is not None and flight["weight_program_id"] != program_id:
            continue
        if status is not None and flight["status"] != status:
            continue
        rows.append(flight)
    items, meta = validate.paginate(db.ordered(rows))
    return response.list_response(items, meta)


# ---------------------------------------------------------- revise conditions
@bp.patch("/flights/<row_id>/conditions")
@authorize("LoadController")
def revise_conditions(row_id):
    payload = validate.body()
    temp = validate.opt_num(payload, "outside_air_temp_c")
    headwind = validate.opt_num(payload, "headwind_component_kt")
    condition = validate.opt_enum(payload, "runway_condition", RUNWAY_CONDITIONS)
    ramp = validate.opt_num(payload, "ramp_fuel_kg", ge=0)
    taxi = validate.opt_num(payload, "taxi_fuel_kg", ge=0)
    trip = validate.opt_num(payload, "trip_fuel_kg", ge=0)

    flight = resolve.flight(row_id)
    aircraft = db.aircraft[flight["aircraft_id"]]
    runway = db.runways[flight["departure_runway_id"]]

    candidate = dict(flight)
    if temp is not None:
        candidate["outside_air_temp_c"] = temp
    if headwind is not None:
        candidate["headwind_component_kt"] = headwind
    if condition is not None:
        candidate["runway_condition"] = condition
    if ramp is not None:
        candidate["ramp_fuel_kg"] = ramp
    if taxi is not None:
        candidate["taxi_fuel_kg"] = taxi
    if trip is not None:
        candidate["trip_fuel_kg"] = trip

    band = select_band(candidate, aircraft)
    check_fuel(candidate["ramp_fuel_kg"], candidate["taxi_fuel_kg"], candidate["trip_fuel_kg"])
    derive_figures(candidate, aircraft, runway, band)

    for key, value in candidate.items():
        flight[key] = value
    db.touch(flight)
    return response.object_response(db.public(flight))


# ------------------------------------------------------------------ depart
@bp.post("/flights/<row_id>/depart")
@authorize("LoadController")
def depart_flight(row_id):
    flight = resolve.flight(row_id)
    if flight["status"] != "LOAD_CONTROLLED":
        fail(ERR_FLIGHT_INVALID_STATE)
    if flight["load_release_state"] != "RELEASED":
        fail(ERR_LOAD_NOT_RELEASED)

    flight["status"] = "DEPARTED"
    db.touch(flight)
    for item in db.flight_cargo(row_id):
        if item["status"] == "ACCEPTED" and not item.get("assigned_compartment_id"):
            item["status"] = "DEFERRED"
            db.touch(item)
    return response.object_response(db.public(flight))


# ------------------------------------------------------------------- close
@bp.post("/flights/<row_id>/close")
@authorize("LoadControlAdmin")
def close_flight(row_id):
    flight = resolve.flight(row_id)
    if flight["status"] != "DEPARTED":
        fail(ERR_FLIGHT_INVALID_STATE)
    if any(audit["status"] != "CLOSED" for audit in db.flight_audits(row_id)):
        fail(ERR_FLIGHT_INVALID_STATE, "Every load audit on the flight must be closed first.")
    flight["status"] = "CLOSED"
    db.touch(flight)
    return response.object_response(db.public(flight))


# ------------------------------------------------------------------ cancel
@bp.post("/flights/<row_id>/cancel")
@authorize("LoadControlAdmin")
def cancel_flight(row_id):
    flight = resolve.flight(row_id)
    if flight["status"] not in ("PLANNING", "LOAD_CONTROLLED"):
        fail(ERR_FLIGHT_INVALID_STATE)

    plans = db.flight_plans(row_id)
    if flight["status"] == "LOAD_CONTROLLED":
        for plan in plans:
            if any(sheet["status"] == "ACCEPTED" for sheet in db.plan_sheets(plan["id"])):
                fail(
                    ERR_FLIGHT_INVALID_STATE,
                    "A load sheet on this flight has already been accepted.",
                )
        plan_statuses = ("DRAFT", "COMPUTED", "RESTRICTED", "SHEET_ISSUED")
        cargo_statuses = ("BOOKED", "ACCEPTED", "LOADED")
    else:
        plan_statuses = ("DRAFT", "COMPUTED", "RESTRICTED")
        cargo_statuses = ("BOOKED", "ACCEPTED")

    for plan in plans:
        if plan["status"] in plan_statuses:
            plan["status"] = "SUPERSEDED"
            db.touch(plan)
            for sheet in db.plan_sheets(plan["id"]):
                if sheet["status"] in ("ISSUED", "REJECTED_BY_CAPTAIN"):
                    sheet["status"] = "SUPERSEDED"
                    db.touch(sheet)

    for item in db.flight_cargo(row_id):
        if item["status"] in cargo_statuses:
            item["status"] = "OFFLOADED"
            item["assigned_compartment_id"] = None
            db.touch(item)

    flight["status"] = "CANCELLED"
    db.touch(flight)
    return response.object_response(db.public(flight))


# --------------------------------------------------------- reverse listings
@bp.get("/flights/<row_id>/load-plans")
@authorize(*ANY_ROLE)
def list_flight_load_plans(row_id):
    validate.pagination()
    status = validate.query_enum(
        "status", ("DRAFT", "COMPUTED", "RESTRICTED", "SHEET_ISSUED", "SUPERSEDED")
    )
    resolve.flight(row_id)
    rows = [
        plan
        for plan in db.flight_plans(row_id)
        if status is None or plan["status"] == status
    ]
    items, meta = validate.paginate(rows)
    return response.list_response(items, meta)


@bp.get("/flights/<row_id>/load-audits")
@authorize(*ANY_ROLE)
def list_flight_load_audits(row_id):
    validate.pagination()
    status = validate.query_enum("status", ("OPEN", "INVESTIGATING", "CLOSED"))
    resolve.flight(row_id)
    rows = [
        audit
        for audit in db.flight_audits(row_id)
        if status is None or audit["status"] == status
    ]
    items, meta = validate.paginate(rows)
    return response.list_response(items, meta)
