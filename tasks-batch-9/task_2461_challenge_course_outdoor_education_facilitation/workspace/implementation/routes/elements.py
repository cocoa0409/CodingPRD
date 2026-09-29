"""Element installation, listing, return-to-service and retirement."""
from flask import Blueprint, g

from db import store, base_row, touch, clock_date, by_created_at
from errors import ApiError, invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_enum, req_int, req_num, req_date
from services import constants as C
from services import derive, serialize, cascade
from services.lookup import get_course, get_element, apply_filters

bp = Blueprint("elements", __name__)
PREFIX = "/challenge-course"

READ_ROLES = ["ProgramDirector", "SafetyOfficer", "Facilitator", "ProfessionalInspector"]


@bp.post(PREFIX + "/elements")
def create_element():
    authorize(["ProgramDirector"])
    payload = body()

    course_id = req_str(payload, "course_id")
    element_name = req_str(payload, "element_name")
    element_type = req_enum(payload, "element_type", C.ELEMENT_TYPES)
    installed_on = req_date(payload, "installed_on")
    due_on = req_date(payload, "next_professional_inspection_due_on")
    min_weight = req_num(payload, "min_participant_weight_kg")
    max_weight = req_num(payload, "max_participant_weight_kg")
    initial_cycle_count = req_int(payload, "initial_cycle_count", required=False, default=0,
                                  minimum=0)

    # element_name is unique within the course, compared case-sensitively.
    for existing in store.elements.values():
        if existing["course_id"] == course_id and existing["element_name"] == element_name:
            raise invalid("element_name must be unique within the course.")

    course = get_course(course_id)

    row = base_row()
    row.update({
        "course_id": course["id"],
        "element_name": element_name,
        "element_type": element_type,
        "installed_on": installed_on,
        "design_life_years": C.DESIGN_LIFE_YEARS[element_type],
        "cycle_life_limit": C.DESIGN_CYCLE_LIMIT[element_type],
        "cumulative_cycle_count": initial_cycle_count,
        "calendar_life_forecast_date": None,
        "usage_life_forecast_date": None,
        "retirement_forecast_date": None,
        "retirement_basis": "CALENDAR",
        "min_participant_weight_kg": min_weight,
        "max_participant_weight_kg": max_weight,
        "next_professional_inspection_due_on": due_on,
        "consecutive_conditional_count": 0,
        "required_belay_set_count": C.REQUIRED_BELAY_SETS_BY_TYPE[element_type],
        "status": "SERVICEABLE",
        "restricting_log_id": None,
    })
    derive.recompute_element_forecast(row)
    store.elements[row["id"]] = row

    derive.recompute_posture(course, bump_version=False)
    return created_response(serialize.element(row))


@bp.get(PREFIX + "/elements/<element_id>")
def read_element(element_id):
    authorize(READ_ROLES)
    element = get_element(element_id)
    return object_response(serialize.element(element))


@bp.get(PREFIX + "/elements")
def list_elements():
    authorize(READ_ROLES)
    limit, offset = pagination()
    rows = by_created_at(list(store.elements.values()))
    rows = apply_filters(rows, {
        "course_id": ("str", "course_id"),
        "status": ("str", "status"),
        "element_type": ("str", "element_type"),
        "restricting_log_id": ("str", "restricting_log_id"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.element(r) for r in window], limit, offset, total)


@bp.post(PREFIX + "/elements/<element_id>/return-to-service")
def return_to_service(element_id):
    authorize(["SafetyOfficer"])
    payload = body()
    req_str(payload, "note")

    element = get_element(element_id)

    # Step 9 — state preconditions.
    if element["status"] == "RETIRED":
        raise ApiError("ERR_ELEMENT_RETIRED")
    if element["status"] == "SERVICEABLE":
        raise ApiError("ERR_ELEMENT_NOT_RESTRICTED")

    # Step 10 — segregation of duties; skipped entirely when there is no
    # restricting log, since then there is no counterparty.
    restricting_log_id = element["restricting_log_id"]
    if restricting_log_id:
        log = store.operational_logs.get(restricting_log_id)
        if log is not None and log["facilitator_id"] == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # Step 17 — no incident referencing the element may still be open.
    for incident in derive.incidents_of_element(element["id"]):
        if incident["status"] in ("REPORTED", "UNDER_REVIEW"):
            raise ApiError("ERR_OPEN_INCIDENT_BLOCKS_SERVICE")

    was_out_of_service = element["status"] == "OUT_OF_SERVICE"

    # Step 18 — the defect has been cleared.
    if was_out_of_service:
        if derive.latest_inspection_outcome(element) != "PASS":
            raise ApiError("ERR_DEFECT_NOT_CLEARED")
    else:
        newest = derive.newest_log(element["id"])
        if newest is None or newest["result"] != "CLEAR":
            raise ApiError("ERR_DEFECT_NOT_CLEARED")

    # Step 36 — the life-expiry clause, out-of-service path only.
    if was_out_of_service:
        if element["retirement_forecast_date"] <= clock_date():
            raise ApiError("ERR_RETIREMENT_CRITERIA_NOT_MET")

    element["status"] = "SERVICEABLE"
    element["restricting_log_id"] = None
    touch(element)

    cascade.release_rigged_equipment(element)
    cascade.restore_blocked_blocks(element)

    course = store.courses.get(element["course_id"])
    if course is not None:
        derive.recompute_posture(course, bump_version=True)
    return object_response(serialize.element(element))


@bp.post(PREFIX + "/elements/<element_id>/retire")
def retire_element(element_id):
    authorize(["ProgramDirector"])
    payload = body()
    req_str(payload, "reason")

    element = get_element(element_id)

    if element["status"] == "RETIRED":
        raise ApiError("ERR_ELEMENT_RETIRED")

    # Step 36 — retirement criteria, then active-block interference.
    criteria_met = (
        element["retirement_forecast_date"] <= clock_date()
        or element["consecutive_conditional_count"] >= C.CONSECUTIVE_CONDITIONAL_RETIREMENT_THRESHOLD
        or derive.latest_inspection_outcome(element) == "FAIL"
    )
    if not criteria_met:
        raise ApiError("ERR_RETIREMENT_CRITERIA_NOT_MET")

    for block in derive.blocks_of_element(element["id"]):
        if block["status"] in C.ACTIVE_BLOCK_STATUSES:
            raise ApiError("ERR_ELEMENT_HAS_ACTIVE_BLOCKS")

    rigged = derive.equipment_of_element(element["id"])

    element["status"] = "RETIRED"
    element["restricting_log_id"] = None
    touch(element)

    for item in rigged:
        item["assigned_element_id"] = None
        if item["status"] == "IN_SERVICE":
            item["status"] = "QUARANTINED"
        touch(item)

    course = store.courses.get(element["course_id"])
    if course is not None:
        derive.recompute_posture(course, bump_version=True)
    return object_response(serialize.element(element))
