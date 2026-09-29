"""Unit orders: award, production, final inspection, delivery and cancellation.

PRD §3.5 and §3.9.
"""

from flask import Blueprint

import calc
import find
import services
import validate
from db import by_created_at, db, new_row, touch
from errors import ApiError
from middleware import ALL_ROLES, PROGRAM_ADMIN, PURCHASING_OFFICER, authorize
from response import created, listing, ok
from timeutil import parse_dt

bp = Blueprint("units", __name__)

UNIT_TYPES = ("PUMPER", "AERIAL", "AMBULANCE")
CANCELLABLE_BUILD_STATUSES = ("SPEC_LOCKED", "PRE_CON_HELD")


@bp.post("/unit-orders")
@authorize(PURCHASING_OFFICER)
def award_unit_order():
    data = validate.body()
    program_id = validate.req_ref(data, "program_id")
    specification_id = validate.req_ref(data, "specification_id")
    unit_type = validate.req_enum(data, "unit_type", UNIT_TYPES)
    # No absolute bound is declared for `award_year`; the program-relative window
    # is rung 53, which sits below the ceiling check, so only a wide sanity range
    # is enforced at rung 3.
    award_year = validate.req_int(data, "award_year", 0, 9999)
    option_unit = validate.opt_bool(data, "option_unit", False)
    gvwr_kg = validate.req_int(data, "gvwr_kg", 4000, 40000)
    front_axle_rating_kg = validate.req_int(data, "front_axle_rating_kg", 1500, 12000)
    rear_axle_rating_kg = validate.req_int(data, "rear_axle_rating_kg", 2000, 30000)
    base_curb_front_kg = validate.req_int(data, "base_curb_front_kg", 500)
    base_curb_rear_kg = validate.req_int(data, "base_curb_rear_kg", 500)
    crew_seat_count = validate.req_int(data, "crew_seat_count", 0, 8)
    engineer = validate.req_str(data, "weight_calc_engineer_user_id", 1, None)

    program = find.program(program_id)
    spec = find.specification(specification_id)

    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE")
    if spec["status"] != "RELEASED":
        raise ApiError("ERR_SPEC_NOT_RELEASED")
    if spec["program_id"] != program["id"]:
        raise ApiError("ERR_SPEC_PROGRAM_MISMATCH")
    if option_unit and int(program["options_exercised_count"]) >= int(
        program["max_option_units"]
    ):
        raise ApiError("ERR_OPTION_LIMIT_EXCEEDED")

    # The award price is computed before anything is written, because rung 52
    # must be able to refuse the write without leaving a single row behind.
    price_cents = calc.award_year_locked_price(program, award_year, option_unit)
    prospective = calc.program_committed_cents(
        program["id"], overrides={"_extra": [price_cents]}
    )
    if prospective > int(program["contract_ceiling_cents"]):
        raise ApiError("ERR_CONTRACT_CEILING_EXCEEDED")

    # Rung 53 sits *below* the ceiling check, which is deliberately unintuitive.
    base_year = int(program["base_year"])
    if award_year < base_year or award_year > base_year + 5:
        raise ApiError("ERR_ESCALATION_YEAR_OUT_OF_RANGE")

    row = new_row(
        {
            "program_id": program["id"],
            "specification_id": spec["id"],
            "chassis_reservation_id": None,
            "unit_type": unit_type,
            "option_unit": option_unit,
            "award_year": award_year,
            "gvwr_kg": gvwr_kg,
            "front_axle_rating_kg": front_axle_rating_kg,
            "rear_axle_rating_kg": rear_axle_rating_kg,
            "base_curb_front_kg": base_curb_front_kg,
            "base_curb_rear_kg": base_curb_rear_kg,
            "crew_seat_count": crew_seat_count,
            "weight_calc_engineer_user_id": engineer,
            "front_axle_load_kg": 0,
            "rear_axle_load_kg": 0,
            "gross_weight_kg": 0,
            "weight_status": "WITHIN_LIMITS",
            "price_cents": price_cents,
            "change_order_total_cents": 0,
            "open_change_order_count": 0,
            "build_status": "SPEC_LOCKED",
            "certification_status": "NOT_SUBMITTED",
            "long_lead_status": "NOT_RESERVED",
            "spec_drift_flag": False,
            "delivered_at": None,
        }
    )
    calc.apply_axle_loads(row)
    db.unit_orders[row["id"]] = row

    if option_unit:
        program["options_exercised_count"] = int(program["options_exercised_count"]) + 1
    services.ledger_sync(program)

    return created(row)


@bp.get("/unit-orders")
@authorize(*ALL_ROLES)
def list_unit_orders():
    limit, offset = validate.pagination()
    program_id = validate.query_filter("program_id")
    specification_id = validate.query_filter("specification_id")
    chassis_reservation_id = validate.query_filter("chassis_reservation_id")
    build_status = validate.query_filter("build_status")
    rows = list(db.unit_orders.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if specification_id is not None:
        rows = [r for r in rows if r["specification_id"] == specification_id]
    if chassis_reservation_id is not None:
        rows = [r for r in rows if r["chassis_reservation_id"] == chassis_reservation_id]
    if build_status is not None:
        rows = [r for r in rows if r["build_status"] == build_status]
    return listing(rows, limit, offset)


@bp.get("/unit-orders/<unit_order_id>")
@authorize(*ALL_ROLES)
def read_unit_order(unit_order_id):
    return ok(find.unit_order(unit_order_id))


@bp.post("/unit-orders/<unit_order_id>/start-production")
@authorize(PROGRAM_ADMIN)
def start_production(unit_order_id):
    unit = find.unit_order(unit_order_id)
    if unit["build_status"] != "PRE_CON_HELD":
        raise ApiError("ERR_INVALID_BUILD_STATE")

    program = db.programs.get(unit["program_id"])
    if program is None or program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_NOT_ACTIVE")

    reservation = None
    if unit["chassis_reservation_id"]:
        reservation = db.reservations.get(unit["chassis_reservation_id"])
    if reservation is None or reservation["status"] != "CONFIRMED":
        raise ApiError("ERR_CHASSIS_NOT_CONFIRMED")

    unit["build_status"] = "IN_PRODUCTION"
    touch(unit)

    # Starting production consumes the slot; a CONSUMED slot is still occupied,
    # so the line's counts come out unchanged — but the line is still mutated.
    reservation["status"] = "CONSUMED"
    touch(reservation)
    line = db.slot_lines.get(reservation["slot_line_id"])
    if line is not None:
        services.sync_slot_line(line)

    return ok(unit)


@bp.post("/unit-orders/<unit_order_id>/final-inspection")
@authorize(PROGRAM_ADMIN)
def final_inspection(unit_order_id):
    unit = find.unit_order(unit_order_id)
    if unit["build_status"] != "MID_CON_HELD":
        raise ApiError("ERR_INVALID_BUILD_STATE")
    # The three gates in ladder order: axle load, then certification, then the
    # open-amendment count. An overloaded, uncertified, amended unit reports the
    # axle overload and nothing else.
    if unit["weight_status"] != "WITHIN_LIMITS":
        raise ApiError("ERR_AXLE_LOAD_EXCEEDED")
    if unit["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_CERTIFICATION_NOT_PASSED")
    if int(unit["open_change_order_count"]) != 0:
        raise ApiError("ERR_OPEN_CHANGE_ORDERS")

    unit["build_status"] = "FINAL_INSPECTED"
    touch(unit)
    return ok(unit)


@bp.post("/unit-orders/<unit_order_id>/deliver")
@authorize(PROGRAM_ADMIN)
def deliver_unit(unit_order_id):
    data = validate.body()
    delivery_date = validate.req_dt(data, "delivery_date")
    training_hours = validate.req_num(data, "training_hours", 0.0, 200.0)
    warranty_months = validate.req_int(data, "warranty_months", 12, 120)

    unit = find.unit_order(unit_order_id)
    if unit["build_status"] != "FINAL_INSPECTED":
        raise ApiError("ERR_INVALID_BUILD_STATE")
    if unit["weight_status"] != "WITHIN_LIMITS":
        raise ApiError("ERR_AXLE_LOAD_EXCEEDED")

    mid_con = _held_mid_construction_trip(unit["id"])
    if mid_con is not None:
        if parse_dt(delivery_date) < parse_dt(mid_con["scheduled_end"]):
            raise ApiError("ERR_DELIVERY_BEFORE_MID_CON")

    program = db.programs.get(unit["program_id"])

    unit["build_status"] = "DELIVERED"
    unit["delivered_at"] = services.clock_raw()
    touch(unit)

    services.create_warranty_startup(
        unit, program, delivery_date, training_hours, warranty_months
    )
    return ok(unit)


def _held_mid_construction_trip(unit_id):
    candidates = [
        t
        for t in db.trips.values()
        if t["unit_order_id"] == unit_id
        and t["trip_type"] == "MID_CONSTRUCTION"
        and t["status"] == "HELD"
    ]
    ordered = by_created_at(candidates)
    return ordered[0] if ordered else None


@bp.post("/unit-orders/<unit_order_id>/cancel")
@authorize(PROGRAM_ADMIN)
def cancel_unit(unit_order_id):
    unit = find.unit_order(unit_order_id)
    if unit["build_status"] not in CANCELLABLE_BUILD_STATUSES:
        raise ApiError("ERR_INVALID_BUILD_STATE")
    if int(unit["open_change_order_count"]) != 0:
        raise ApiError("ERR_OPEN_CHANGE_ORDERS")

    program = db.programs.get(unit["program_id"])

    # The unit leaves the ledger's input set first, which is what decommits it.
    unit["build_status"] = "CANCELLED"
    touch(unit)

    reservation = None
    if unit["chassis_reservation_id"]:
        reservation = db.reservations.get(unit["chassis_reservation_id"])
    if reservation is not None and reservation["status"] in ("RESERVED", "CONFIRMED"):
        # Cancellation releases the hold but does not put the unit at risk: the
        # unit is already terminal, so the at-risk hop cannot apply to it.
        services.release_reservation(reservation, "RELEASED")
    unit["chassis_reservation_id"] = None

    if unit["option_unit"] and program is not None:
        program["options_exercised_count"] = max(
            int(program["options_exercised_count"]) - 1, 0
        )

    if program is not None:
        services.ledger_sync(program)

    return ok(unit)
