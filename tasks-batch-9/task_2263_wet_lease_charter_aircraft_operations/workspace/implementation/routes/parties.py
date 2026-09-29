"""Lessees, airframes and crew members (PRD 3.1)."""

from flask import Blueprint, request

from db import db, new_row, touch, public
from errors import ApiError
from middleware import (
    require, authenticate, authorize, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, MAINTENANCE_CONTROLLER, BILLING_ADMIN,
)
from response import object_response, pagination, paged
from routes.common import find_lessee, find_aircraft, find_crew, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("parties", __name__)


# ------------------------------------------------------------------ lessees

@bp.post("/wetlease/lessees")
def create_lessee():
    require((BILLING_ADMIN,))
    body = V.json_body()
    name = V.req_str(body, "name")
    icao_code = V.req_icao(body, "icao_code", 3)
    home_base_icao = V.req_icao(body, "home_base_icao", 4)
    credit_limit = V.req_int(body, "credit_limit_usd_cents", minimum=0)

    row = new_row()
    row.update({
        "name": name,
        "icao_code": icao_code,
        "home_base_icao": home_base_icao,
        "credit_limit_usd_cents": credit_limit,
        "outstanding_balance_usd_cents": 0,
        "status": "ACTIVE",
    })
    db.lessees[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/wetlease/lessees/<lessee_id>")
def get_lessee(lessee_id):
    actor = require((BILLING_ADMIN, LESSOR_OPS, LESSEE))
    lessee = find_lessee(lessee_id)
    check_ownership(actor, "lessee", lessee)
    W.recompute_lessee_balance(lessee)
    return object_response(public(lessee))


@bp.post("/wetlease/lessees/<lessee_id>/suspend")
def suspend_lessee(lessee_id):
    require((BILLING_ADMIN,))
    V.json_body()
    lessee = find_lessee(lessee_id)
    if lessee["status"] != "ACTIVE":
        raise ApiError("ERR_LESSEE_INVALID_STATE")
    lessee["status"] = "SUSPENDED"
    touch(lessee)
    return object_response(public(lessee))


@bp.post("/wetlease/lessees/<lessee_id>/reinstate")
def reinstate_lessee(lessee_id):
    require((BILLING_ADMIN,))
    V.json_body()
    lessee = find_lessee(lessee_id)
    if lessee["status"] != "SUSPENDED":
        raise ApiError("ERR_LESSEE_INVALID_STATE")
    lessee["status"] = "ACTIVE"
    touch(lessee)
    return object_response(public(lessee))


# ------------------------------------------------------------------ aircraft

@bp.post("/wetlease/aircraft")
def create_aircraft():
    require((MAINTENANCE_CONTROLLER,))
    body = V.json_body()
    tail_number = V.req_str(body, "tail_number", min_len=5, max_len=7)
    type_designator = V.req_str(body, "type_designator")
    type_family = V.req_str(body, "type_family")
    seat_count = V.req_int(body, "seat_count", minimum=1)
    mtow_kg = V.req_int(body, "mtow_kg", minimum=1)
    program_ref = V.req_str(body, "maintenance_program_ref")
    airframe_hours = V.opt_num(body, "airframe_hours_total", default=0, minimum=0)
    hours_since = V.opt_num(body, "hours_since_last_check", default=0, minimum=0)
    cycles_since = V.opt_int(body, "cycles_since_last_check", default=0, minimum=0)

    for existing in db.aircraft.values():
        if existing["tail_number"] == tail_number:
            raise ApiError("ERR_DUPLICATE_TAIL_NUMBER")

    row = new_row()
    row.update({
        "tail_number": tail_number,
        "type_designator": type_designator,
        "type_family": type_family,
        "seat_count": seat_count,
        "mtow_kg": mtow_kg,
        "maintenance_program_ref": program_ref,
        "airframe_hours_total": C.money2(airframe_hours),
        "hours_since_last_check": C.money2(hours_since),
        "cycles_since_last_check": cycles_since,
        "assigned_lease_id": None,
        "status": "AVAILABLE",
    })
    db.aircraft[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/wetlease/aircraft/<aircraft_id>")
def get_aircraft(aircraft_id):
    actor = require((MAINTENANCE_CONTROLLER, LESSOR_OPS, LESSEE))
    aircraft = find_aircraft(aircraft_id)
    if actor.is_lessee and aircraft["assigned_lease_id"] is not None:
        check_ownership(actor, "aircraft", aircraft)
    return object_response(public(aircraft))


@bp.get("/wetlease/aircraft")
def list_aircraft():
    actor = require((MAINTENANCE_CONTROLLER, LESSOR_OPS, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.aircraft.values()), request.args, {
        "assigned_lease_id": "assigned_lease_id",
        "status": "status",
        "type_designator": "type_designator",
        "type_family": "type_family",
    })
    rows = scope_for_lessee(actor, "aircraft", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/aircraft/<aircraft_id>/maintenance-events")
def maintenance_event(aircraft_id):
    require((MAINTENANCE_CONTROLLER,))
    body = V.json_body()
    event_type = V.req_enum(body, "event_type", (
        "GROUND_SCHEDULED", "GROUND_AOG", "RETURN_TO_SERVICE", "RETIRE"))
    V.opt_str(body, "note")
    aircraft = find_aircraft(aircraft_id)
    status = aircraft["status"]

    if event_type == "GROUND_SCHEDULED":
        if status not in ("AVAILABLE", "ASSIGNED"):
            raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
        aircraft["status"] = "IN_MAINTENANCE"
        touch(aircraft)
    elif event_type == "GROUND_AOG":
        if status not in ("AVAILABLE", "ASSIGNED"):
            raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
        aircraft["status"] = "AOG"
        touch(aircraft)
        lease_id = aircraft["assigned_lease_id"]
        if lease_id:
            lease = db.leases.get(lease_id)
            for leg in W.legs_of_aircraft(aircraft["id"]):
                if leg["status"] in ("SCHEDULED", "DISPATCHED"):
                    W.cancel_leg(leg, "LESSOR", "TECHNICAL")
            if lease is not None:
                W.suspend_lease(lease, "AIRFRAME_AOG", "TECHNICAL")
    elif event_type == "RETURN_TO_SERVICE":
        if status not in ("IN_MAINTENANCE", "AOG"):
            raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
        aircraft["hours_since_last_check"] = 0.0
        aircraft["cycles_since_last_check"] = 0
        aircraft["status"] = "ASSIGNED" if aircraft["assigned_lease_id"] else "AVAILABLE"
        touch(aircraft)
    else:  # RETIRE
        if status not in ("AVAILABLE", "IN_MAINTENANCE", "AOG"):
            raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
        if aircraft["assigned_lease_id"] is not None:
            raise ApiError("ERR_AIRCRAFT_UNAVAILABLE")
        aircraft["status"] = "RETIRED"
        touch(aircraft)

    return object_response(public(aircraft))


# ------------------------------------------------------------------ crew members

@bp.post("/wetlease/crew-members")
def create_crew_member():
    require((LESSOR_OPS,))
    body = V.json_body()
    full_name = V.req_str(body, "full_name")
    employee_no = V.req_str(body, "employee_no")
    crew_role = V.req_enum(body, "crew_role", ("CAPTAIN", "FIRST_OFFICER", "CABIN"))
    type_ratings = V.req_str_list(body, "type_ratings", non_empty=True)

    row = new_row()
    row.update({
        "full_name": full_name,
        "employee_no": employee_no,
        "crew_role": crew_role,
        "type_ratings": type_ratings,
        "rolling_duty_minutes_7d": 0,
        "rolling_block_minutes_28d": 0,
        "status": "ACTIVE",
    })
    db.crew_members[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/wetlease/crew-members/<crew_member_id>")
def get_crew_member(crew_member_id):
    require((LESSOR_OPS, MAINTENANCE_CONTROLLER))
    crew = find_crew(crew_member_id)
    W.recompute_crew(crew["id"])
    return object_response(public(crew))
