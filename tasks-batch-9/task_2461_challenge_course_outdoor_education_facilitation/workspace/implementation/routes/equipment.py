"""Belay hardware inventory and out-of-block usage logging."""
from flask import Blueprint

from db import store, base_row, touch, clock_date, by_created_at
from errors import ApiError, invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_enum, req_int, req_date
from services import constants as C
from services import derive, serialize, cascade
from services.lookup import get_course, get_element, get_equipment, apply_filters

bp = Blueprint("equipment", __name__)
PREFIX = "/challenge-course"


@bp.post(PREFIX + "/belay-equipment")
def create_equipment():
    authorize(["ProgramDirector", "SafetyOfficer"])
    payload = body()

    course_id = req_str(payload, "course_id")
    equipment_kind = req_enum(payload, "equipment_kind", C.EQUIPMENT_KINDS)
    serial_number = req_str(payload, "serial_number")
    manufactured_on = req_date(payload, "manufactured_on")
    max_cycles = req_int(payload, "max_cycles", minimum=1)
    assigned_element_id = req_str(payload, "assigned_element_id", required=False, default=None)
    first_use_on = req_date(payload, "first_use_on", required=False, default=None)
    initial_usage_cycles = req_int(payload, "initial_usage_cycles", required=False, default=0,
                                  minimum=0)

    # serial_number is unique within the course, compared case-sensitively.
    for existing in store.belay_equipment.values():
        if existing["course_id"] == course_id and existing["serial_number"] == serial_number:
            raise invalid("serial_number must be unique within the course.")

    course = get_course(course_id)
    element = get_element(assigned_element_id) if assigned_element_id else None

    # Step 27 — the rigged element must sit on the same course.
    if element is not None and element["course_id"] != course["id"]:
        raise ApiError("ERR_ELEMENT_COURSE_MISMATCH")

    row = base_row()
    row.update({
        "course_id": course["id"],
        "assigned_element_id": element["id"] if element is not None else None,
        "equipment_kind": equipment_kind,
        "serial_number": serial_number,
        "manufactured_on": manufactured_on,
        "first_use_on": first_use_on,
        "usage_cycles": initial_usage_cycles,
        "max_cycles": max_cycles,
        "mfg_life_forecast_date": None,
        "service_life_forecast_date": None,
        "retirement_forecast_date": None,
        "retirement_basis": "MANUFACTURE",
        "status": "IN_SERVICE",
    })
    derive.recompute_equipment_forecast(row)
    store.belay_equipment[row["id"]] = row

    # Installing hardware refreshes the element's readiness and the course
    # counters, both of which are derived on read; posture itself only moves if a
    # clause actually flipped.
    derive.recompute_posture(course, bump_version=False)
    return created_response(serialize.belay_equipment(row))


@bp.get(PREFIX + "/belay-equipment/<equipment_id>")
def read_equipment(equipment_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    row = get_equipment(equipment_id)
    return object_response(serialize.belay_equipment(row))


@bp.get(PREFIX + "/belay-equipment")
def list_equipment():
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    limit, offset = pagination()
    rows = by_created_at(list(store.belay_equipment.values()))
    rows = apply_filters(rows, {
        "course_id": ("str", "course_id"),
        "assigned_element_id": ("str", "assigned_element_id"),
        "status": ("str", "status"),
        "equipment_kind": ("str", "equipment_kind"),
        "retirement_basis": ("str", "retirement_basis"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.belay_equipment(r) for r in window], limit, offset, total)


@bp.post(PREFIX + "/belay-equipment/<equipment_id>/log-usage")
def log_usage(equipment_id):
    authorize(["Facilitator", "SafetyOfficer"])
    payload = body()
    cycles = req_int(payload, "cycles", minimum=1)

    item = get_equipment(equipment_id)

    # Step 9.
    if item["status"] == "RETIRED":
        raise ApiError("ERR_EQUIPMENT_RETIRED")

    element = (store.elements.get(item["assigned_element_id"])
               if item["assigned_element_id"] else None)
    was_ready = derive.belay_ready(element) if element is not None else False

    item["usage_cycles"] = item["usage_cycles"] + cycles
    if item["first_use_on"] is None:
        item["first_use_on"] = clock_date()
    derive.recompute_equipment_forecast(item)
    if item["usage_cycles"] >= item["max_cycles"]:
        item["status"] = "RETIRED"
    touch(item)

    if element is not None:
        cascade.propagate_belay_loss(element, was_ready)

    return object_response(serialize.belay_equipment(item))
