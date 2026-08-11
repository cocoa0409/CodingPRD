"""The adaptive equipment cage: items, inspections and reservations."""

from flask import Blueprint

import calc
import engine
import enums
import lookups as L
import serial
from ctx import (
    Body,
    Refs,
    check_transition,
    check_version,
    endpoint,
    pagination,
    paginate,
    resolve_one,
)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, sort_rows, touch

bp = Blueprint("equipment", __name__)

RESERVATION_TERMINALS = (
    "RETURNED_GOOD",
    "RETURNED_DAMAGED",
    "RELEASED",
    "VOIDED_INSPECTION_FAIL",
)
INSPECTION_EDGES = {
    "PASS": ("INSPECTION_DUE", "OUT_OF_SERVICE"),
    "FAIL": ("SERVICEABLE", "INSPECTION_DUE"),
    "RETIRE": ("SERVICEABLE", "INSPECTION_DUE", "OUT_OF_SERVICE"),
}


def _reservation_session(context):
    reservation = db.get("equipment_reservations", context.params.get("reservation_id"))
    enrollment = L.enrollment_of_reservation(reservation) if reservation else None
    return L.session_of_enrollment(enrollment) if enrollment else None


# ---------------------------------------------------------------------------
# equipment items
# ---------------------------------------------------------------------------

@bp.route("/recreation/equipment-items", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def create_item(context):
    body = Body(context.body)
    item_kind = body.req_enum("item_kind", enums.ITEM_KINDS)
    model_code = body.req_string("model_code")
    size_code = body.req_string("size_code")
    weight_capacity_kg = body.req_int("weight_capacity_kg", minimum=0)
    serial_number = body.opt_string("serial_number", None)
    inspection_due_date = body.opt_date("inspection_due_date", None)
    pooled_total = body.opt_int("pooled_total", 1, minimum=1)
    body.check_enums()

    if item_kind == "SERIALIZED":
        if serial_number is None:
            raise ApiError("ERR_VALIDATION", "serial_number is required for a SERIALIZED item.")
        if inspection_due_date is None:
            raise ApiError(
                "ERR_VALIDATION", "inspection_due_date is required for a SERIALIZED item."
            )
        pooled_total = 1
    else:
        serial_number = None
        inspection_due_date = None

    row = insert(
        "equipment_items",
        {
            "item_kind": item_kind,
            "model_code": model_code,
            "size_code": size_code,
            "weight_capacity_kg": weight_capacity_kg,
            "serial_number": serial_number,
            "inspection_due_date": inspection_due_date,
            "condition_status": "SERVICEABLE",
            "pooled_total": pooled_total,
            "pooled_available": pooled_total,
            "pooled_held": 0,
            "pooled_checked_out": 0,
        },
    )
    return ok(serial.dump(row), 201)


@bp.route("/recreation/equipment-items/<item_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_item(context, item_id):
    return ok(serial.dump(resolve_one("equipment", item_id)))


@bp.route("/recreation/equipment-items/<item_id>/inspections", methods=["POST"])
@endpoint(roles=("ProgramAdmin",))
def record_inspection(context, item_id):
    item = resolve_one("equipment", item_id)
    body = Body(context.body)
    disposition = body.req_enum("disposition", enums.DISPOSITIONS)
    body.check_enums()
    check_transition(item["condition_status"], INSPECTION_EDGES.get(disposition, ()), ("RETIRED",))

    if disposition == "PASS":
        item["condition_status"] = "SERVICEABLE"
        item["inspection_due_date"] = engine.next_inspection_due_date()
        touch(item)
    elif disposition == "FAIL":
        engine.apply_item_condition(item, "OUT_OF_SERVICE")
    else:
        engine.apply_item_condition(item, "RETIRED")
    return ok(serial.dump(item))


# ---------------------------------------------------------------------------
# reservations
# ---------------------------------------------------------------------------

@bp.route("/recreation/equipment-reservations", methods=["POST"])
@endpoint(roles=("ActivityLead", "IntakeCoordinator"))
def create_reservation(context):
    raw = context.body
    refs = Refs()
    if isinstance(raw.get("enrollment_id"), str):
        refs.add("enrollment", raw["enrollment_id"], path=False)
    if isinstance(raw.get("equipment_item_id"), str):
        refs.add("equipment", raw["equipment_item_id"], path=False)
    refs.resolve()

    body = Body(raw)
    enrollment_id = body.req_string("enrollment_id")
    equipment_item_id = body.req_string("equipment_item_id")
    expected_version = body.req_int("expected_item_version")
    body.check_enums()

    enrollment = resolve_one("enrollment", enrollment_id)
    item = resolve_one("equipment", equipment_item_id)
    check_version(expected_version, item)

    session = L.session_of_enrollment(enrollment)
    program = L.program_of_session(session)
    participant = L.participant_of_enrollment(enrollment)

    if not calc.equipment_fit_ok(item, program, participant):          # rung 49
        raise ApiError("ERR_EQUIPMENT_FIT_MISMATCH")
    if not calc.equipment_condition_ok(item, session):                 # rung 50
        raise ApiError("ERR_EQUIPMENT_INSPECTION_OVERDUE")
    if not calc.equipment_available_ok(item):                          # rung 51
        raise ApiError("ERR_EQUIPMENT_UNAVAILABLE")

    row = insert(
        "equipment_reservations",
        {
            "enrollment_id": enrollment["id"],
            "equipment_item_id": item["id"],
            "return_condition": None,
            "status": "HELD",
        },
    )
    engine.refresh_item_counters(item)
    return ok(serial.dump(row), 201)


@bp.route("/recreation/equipment-reservations", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def list_reservations(context):
    limit, offset = pagination(context)
    rows = sort_rows(db.rows("equipment_reservations"))
    enrollment_id = context.q("enrollment_id")
    item_id = context.q("equipment_item_id")
    status = context.q("status")
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if item_id is not None:
        rows = [r for r in rows if r["equipment_item_id"] == item_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list(serial.dump_all(page), limit, offset, total)


@bp.route("/recreation/equipment-reservations/<reservation_id>", methods=["GET"])
@endpoint(roles=enums.STAFF_ROLES)
def read_reservation(context, reservation_id):
    return ok(serial.dump(resolve_one("reservation", reservation_id)))


@bp.route("/recreation/equipment-reservations/<reservation_id>/check-out", methods=["POST"])
@endpoint(roles=("ActivityLead",), delivery=_reservation_session)
def check_out_reservation(context, reservation_id):
    reservation = resolve_one("reservation", reservation_id)
    check_transition(reservation["status"], ("HELD",), RESERVATION_TERMINALS)
    item = L.item_of_reservation(reservation)
    enrollment = L.enrollment_of_reservation(reservation)
    session = L.session_of_enrollment(enrollment)
    if session["status"] != "STAFFING_LOCKED":
        raise ApiError("ERR_INVALID_STATE", "The session is not staffing-locked.")
    if enrollment["enrollment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "The enrolment is not confirmed.")
    if item["condition_status"] != "SERVICEABLE":
        raise ApiError("ERR_EQUIPMENT_INSPECTION_OVERDUE")
    reservation["status"] = "CHECKED_OUT"
    touch(reservation)
    engine.refresh_item_counters(item)
    return ok(serial.dump(reservation))


@bp.route("/recreation/equipment-reservations/<reservation_id>/return", methods=["POST"])
@endpoint(roles=("ActivityLead",), delivery=_reservation_session)
def return_reservation(context, reservation_id):
    reservation = resolve_one("reservation", reservation_id)
    body = Body(context.body)
    return_condition = body.req_enum("return_condition", enums.RETURN_CONDITIONS)
    body.check_enums()
    check_transition(reservation["status"], ("CHECKED_OUT",), RESERVATION_TERMINALS)
    item = L.item_of_reservation(reservation)
    reservation["return_condition"] = return_condition
    reservation["status"] = (
        "RETURNED_GOOD" if return_condition == "GOOD" else "RETURNED_DAMAGED"
    )
    touch(reservation)
    engine.refresh_item_counters(item)
    if return_condition == "DAMAGED":
        engine.apply_item_condition(item, "OUT_OF_SERVICE")
    return ok(serial.dump(reservation))


@bp.route("/recreation/equipment-reservations/<reservation_id>/release", methods=["POST"])
@endpoint(roles=("ActivityLead", "IntakeCoordinator"))
def release_reservation(context, reservation_id):
    reservation = resolve_one("reservation", reservation_id)
    check_transition(reservation["status"], ("HELD",), RESERVATION_TERMINALS)
    item = L.item_of_reservation(reservation)
    reservation["status"] = "RELEASED"
    touch(reservation)
    engine.refresh_item_counters(item)
    return ok(serial.dump(reservation))
