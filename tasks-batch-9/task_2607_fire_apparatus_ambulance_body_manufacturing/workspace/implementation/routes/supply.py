"""Long-lead supply and committee floor space.

Supplier slot lines, chassis reservations (Cascade C), plant bays and inspection
trips — PRD §3.6 and §3.7.
"""

from flask import Blueprint

import calc
import find
import services
import validate
from db import db, new_row, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    COMMITTEE_REP,
    PROGRAM_ADMIN,
    authorize,
    committee_scope_for_trip,
)
from response import created, listing, ok
from timeutil import parse_dt

bp = Blueprint("supply", __name__)

COMPONENT_TYPES = ("CHASSIS", "AERIAL_DEVICE", "PATIENT_MODULE")
TRIP_TYPES = ("PRE_CONSTRUCTION", "MID_CONSTRUCTION", "FINAL")


# ==========================================================================
# Supplier slot lines
# ==========================================================================


@bp.post("/slot-lines")
@authorize(PROGRAM_ADMIN)
def register_slot_line():
    data = validate.body()
    supplier_name = validate.req_str(data, "supplier_name", 1, 120)
    component_type = validate.req_enum(data, "component_type", COMPONENT_TYPES)
    total_slot_count = validate.req_int(data, "total_slot_count", 1, 50)
    changeover_buffer_days = validate.opt_int(data, "changeover_buffer_days", 0, 30, 7)

    row = new_row(
        {
            "supplier_name": supplier_name,
            "component_type": component_type,
            "total_slot_count": total_slot_count,
            "changeover_buffer_days": changeover_buffer_days,
            "reserved_slot_count": 0,
            "available_slot_count": total_slot_count,
        }
    )
    db.slot_lines[row["id"]] = row
    return created(row)


@bp.get("/slot-lines")
@authorize(*ALL_ROLES)
def list_slot_lines():
    limit, offset = validate.pagination()
    component_type = validate.query_filter("component_type")
    rows = list(db.slot_lines.values())
    if component_type is not None:
        rows = [r for r in rows if r["component_type"] == component_type]
    return listing(rows, limit, offset)


@bp.get("/slot-lines/<slot_line_id>")
@authorize(*ALL_ROLES)
def read_slot_line(slot_line_id):
    return ok(find.slot_line(slot_line_id))


# ==========================================================================
# Chassis reservations
# ==========================================================================


@bp.post("/chassis-reservations")
@authorize(PROGRAM_ADMIN)
def book_reservation():
    data = validate.body()
    program_id = validate.req_ref(data, "program_id")
    slot_line_id = validate.req_ref(data, "slot_line_id")
    unit_order_id = validate.opt_ref(data, "unit_order_id")
    slot_start_date = validate.req_dt(data, "slot_start_date")
    slot_end_date = validate.req_dt(data, "slot_end_date")
    reserved_price_cents = validate.req_int(data, "reserved_price_cents", 0)
    expiry_at = validate.req_dt(data, "expiry_at")
    expected_slot_line_version = validate.req_int(
        data, "expected_slot_line_version", 0
    )

    program = find.program(program_id)
    unit = find.unit_order(unit_order_id) if unit_order_id is not None else None
    line = find.slot_line(slot_line_id)

    # Rung 8 — the long-lead hold is booked against an observed free-slot picture.
    if expected_slot_line_version != int(line["version"]):
        raise ApiError("ERR_STALE_SLOT_LINE_VERSION")

    if unit is not None and unit["program_id"] != program["id"]:
        raise ApiError("ERR_RESERVATION_UNIT_MISMATCH")

    start = parse_dt(slot_start_date)
    if parse_dt(slot_end_date) <= start or parse_dt(expiry_at) <= start:
        raise ApiError("ERR_INVALID_SLOT_WINDOW")

    if calc.slot_window_conflicts(line, slot_start_date, slot_end_date):
        raise ApiError("ERR_SLOT_WINDOW_CONFLICT")

    if int(line["available_slot_count"]) <= 0:
        raise ApiError("ERR_SLOT_LINE_EXHAUSTED")

    row = new_row(
        {
            "program_id": program["id"],
            "slot_line_id": line["id"],
            "unit_order_id": unit["id"] if unit is not None else None,
            "slot_start_date": slot_start_date,
            "slot_end_date": slot_end_date,
            "reserved_price_cents": reserved_price_cents,
            "expiry_at": expiry_at,
            "status": "RESERVED",
            "confirmed_at": None,
        }
    )
    db.reservations[row["id"]] = row
    services.sync_slot_line(line)

    if unit is not None:
        unit["chassis_reservation_id"] = row["id"]
        unit["long_lead_status"] = "RESERVED"
        touch(unit)

    return created(row)


@bp.get("/chassis-reservations")
@authorize(*ALL_ROLES)
def list_reservations():
    limit, offset = validate.pagination()
    program_id = validate.query_filter("program_id")
    slot_line_id = validate.query_filter("slot_line_id")
    unit_order_id = validate.query_filter("unit_order_id")
    status = validate.query_filter("status")
    rows = list(db.reservations.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if slot_line_id is not None:
        rows = [r for r in rows if r["slot_line_id"] == slot_line_id]
    if unit_order_id is not None:
        rows = [r for r in rows if r["unit_order_id"] == unit_order_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, limit, offset)


@bp.get("/chassis-reservations/<reservation_id>")
@authorize(*ALL_ROLES)
def read_reservation(reservation_id):
    return ok(find.reservation(reservation_id))


@bp.post("/chassis-reservations/<reservation_id>/confirm")
@authorize(PROGRAM_ADMIN)
def confirm_reservation(reservation_id):
    reservation = find.reservation(reservation_id)
    if reservation["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_RESERVATION_STATE")
    if not reservation["unit_order_id"]:
        raise ApiError("ERR_RESERVATION_UNASSIGNED")

    reservation["status"] = "CONFIRMED"
    reservation["confirmed_at"] = services.clock_raw()
    touch(reservation)

    unit = db.unit_orders.get(reservation["unit_order_id"])
    if unit is not None:
        unit["long_lead_status"] = "CONFIRMED"
        touch(unit)

    return ok(reservation)


@bp.post("/chassis-reservations/<reservation_id>/release")
@authorize(PROGRAM_ADMIN)
def release_reservation(reservation_id):
    reservation = find.reservation(reservation_id)
    if reservation["status"] not in ("RESERVED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_RESERVATION_STATE")
    services.release_reservation(reservation, "RELEASED")
    return ok(reservation)


# ==========================================================================
# Plant bays — immutable, so no `updated_at` and no `version`
# ==========================================================================


@bp.post("/plant-bays")
@authorize(PROGRAM_ADMIN)
def register_plant_bay():
    data = validate.body()
    name = validate.req_str(data, "name", 1, 80)
    max_concurrent_visitors = validate.req_int(data, "max_concurrent_visitors", 1, 60)
    row = new_row(
        {"name": name, "max_concurrent_visitors": max_concurrent_visitors},
        versioned=False,
    )
    db.plant_bays[row["id"]] = row
    return created(row)


@bp.get("/plant-bays")
@authorize(*ALL_ROLES)
def list_plant_bays():
    limit, offset = validate.pagination()
    return listing(list(db.plant_bays.values()), limit, offset)


@bp.get("/plant-bays/<plant_bay_id>")
@authorize(*ALL_ROLES)
def read_plant_bay(plant_bay_id):
    return ok(find.plant_bay(plant_bay_id))


# ==========================================================================
# Inspection trips
# ==========================================================================


@bp.post("/inspection-trips")
@authorize(PROGRAM_ADMIN)
def schedule_trip():
    data = validate.body()
    unit_order_id = validate.req_ref(data, "unit_order_id")
    plant_bay_id = validate.req_ref(data, "plant_bay_id")
    trip_type = validate.req_enum(data, "trip_type", TRIP_TYPES)
    scheduled_start = validate.req_dt(data, "scheduled_start")
    scheduled_end = validate.req_dt(data, "scheduled_end")
    committee_size = validate.req_int(data, "committee_size", 1, 40)

    unit = find.unit_order(unit_order_id)
    bay = find.plant_bay(plant_bay_id)

    if parse_dt(scheduled_end) <= parse_dt(scheduled_start):
        raise ApiError("ERR_INVALID_TRIP_WINDOW")

    # Rung 40 — closed windows, and the constraint is the aggregate sum of
    # committee sizes over every intersecting window, never a pairwise collision.
    occupied = calc.bay_occupied_visitors(bay["id"], scheduled_start, scheduled_end)
    if occupied + committee_size > int(bay["max_concurrent_visitors"]):
        raise ApiError("ERR_BAY_CAPACITY_EXCEEDED")

    row = new_row(
        {
            "unit_order_id": unit["id"],
            "plant_bay_id": bay["id"],
            "trip_type": trip_type,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "committee_size": committee_size,
            "status": "SCHEDULED",
            "held_at": None,
        }
    )
    db.trips[row["id"]] = row
    return created(row)


@bp.get("/inspection-trips")
@authorize(*ALL_ROLES)
def list_trips():
    limit, offset = validate.pagination()
    unit_order_id = validate.query_filter("unit_order_id")
    plant_bay_id = validate.query_filter("plant_bay_id")
    trip_type = validate.query_filter("trip_type")
    status = validate.query_filter("status")
    rows = list(db.trips.values())
    if unit_order_id is not None:
        rows = [r for r in rows if r["unit_order_id"] == unit_order_id]
    if plant_bay_id is not None:
        rows = [r for r in rows if r["plant_bay_id"] == plant_bay_id]
    if trip_type is not None:
        rows = [r for r in rows if r["trip_type"] == trip_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows, limit, offset)


@bp.get("/inspection-trips/<inspection_trip_id>")
@authorize(*ALL_ROLES)
def read_trip(inspection_trip_id):
    return ok(find.inspection_trip(inspection_trip_id))


@bp.post("/inspection-trips/<inspection_trip_id>/hold")
@authorize(PROGRAM_ADMIN, COMMITTEE_REP)
def hold_trip(inspection_trip_id):
    trip = find.inspection_trip(inspection_trip_id)
    committee_scope_for_trip(trip)
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TRIP_STATE")

    # Rung 41 — at most one trip of a given type may ever be held on a unit.
    for other in db.trips.values():
        if (
            other["id"] != trip["id"]
            and other["unit_order_id"] == trip["unit_order_id"]
            and other["trip_type"] == trip["trip_type"]
            and other["status"] == "HELD"
        ):
            raise ApiError("ERR_TRIP_TYPE_ALREADY_HELD")

    unit = db.unit_orders.get(trip["unit_order_id"])
    build_status = unit["build_status"] if unit is not None else None

    # The milestone must match the build progress. PRE_CONSTRUCTION carries no
    # such requirement — it merely advances the unit when the unit is ready.
    if trip["trip_type"] == "MID_CONSTRUCTION" and build_status != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_BUILD_STATE")
    if trip["trip_type"] == "FINAL" and build_status != "FINAL_INSPECTED":
        raise ApiError("ERR_INVALID_BUILD_STATE")

    trip["status"] = "HELD"
    trip["held_at"] = services.clock_raw()
    touch(trip)

    if unit is not None:
        if trip["trip_type"] == "PRE_CONSTRUCTION" and build_status == "SPEC_LOCKED":
            unit["build_status"] = "PRE_CON_HELD"
            touch(unit)
        elif trip["trip_type"] == "MID_CONSTRUCTION" and build_status == "IN_PRODUCTION":
            unit["build_status"] = "MID_CON_HELD"
            touch(unit)

    return ok(trip)


@bp.post("/inspection-trips/<inspection_trip_id>/cancel")
@authorize(PROGRAM_ADMIN, COMMITTEE_REP)
def cancel_trip(inspection_trip_id):
    trip = find.inspection_trip(inspection_trip_id)
    committee_scope_for_trip(trip)
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_TRIP_STATE")
    trip["status"] = "CANCELLED"
    touch(trip)
    return ok(trip)
