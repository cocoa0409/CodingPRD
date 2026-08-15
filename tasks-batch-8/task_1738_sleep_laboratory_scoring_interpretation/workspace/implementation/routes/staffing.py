"""Technologist night staffing assignments (PRD 3.3)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_CAPACITY_WOULD_BE_VIOLATED,
    ERR_STAFFING_INVALID_STATE,
    ERR_STAFFING_NOT_OWN,
    ERR_TECH_DOUBLE_BOOKED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.calculations import confirmed_capacity, occupied_inlab
from services.core import new_record, touch
from util import CLOCK
from validate import get_body, req_str, req_int, opt_int, req_date, require_path_resource, require_body_ref

bp = Blueprint("staffing", __name__)


@bp.post("/staffing-assignments")
def create_staffing_assignment():
    authorized(["LabDirector"])
    body = get_body()
    # Priority 3: body FK existence.
    require_body_ref("technologists", body.get("technologist_id"))
    # Priority 4: shape.
    technologist_id = req_str(body, "technologist_id")
    shift_date = req_date(body, "shift_date")
    patient_capacity = opt_int(body, "patient_capacity", 2, minimum=1, maximum=4)
    # Priority 11: one non-CANCELLED assignment per (technologist, night).
    for existing in db["staffing_assignments"].values():
        if (existing["technologist_id"] == technologist_id
                and existing["shift_date"] == shift_date
                and existing["status"] != "CANCELLED"):
            raise_error(ERR_TECH_DOUBLE_BOOKED,
                        "technologist already has a non-CANCELLED assignment on this shift_date")
    rec = new_record("staffing_assignments", {
        "technologist_id": technologist_id,
        "shift_date": shift_date,
        "patient_capacity": patient_capacity,
        "confirmed_at": None,
        "status": "PLANNED",
    })
    return success_object(public(rec), status=201)


@bp.get("/staffing-assignments")
def list_staffing_assignments():
    return list_response("staffing_assignments",
                         query_filters("technologist_id", "shift_date", "status"))


@bp.get("/staffing-assignments/<staffingAssignmentId>")
def get_staffing_assignment(staffingAssignmentId):
    return get_one("staffing_assignments", staffingAssignmentId)


@bp.post("/staffing-assignments/<staffingAssignmentId>/confirm")
def confirm_staffing_assignment(staffingAssignmentId):
    caller = authorized(["SleepTechnologist"])
    assignment = require_path_resource("staffing_assignments", staffingAssignmentId)
    # Priority 5: confirmation is personal to the assigned technologist.
    if caller.user_id != assignment["technologist_id"]:
        raise_error(ERR_STAFFING_NOT_OWN,
                    "X-User-ID must equal the assignment's technologist_id")
    if assignment["status"] != "PLANNED":
        raise_error(ERR_STAFFING_INVALID_STATE,
                    f"confirm requires PLANNED, found {assignment['status']}")
    assignment["status"] = "CONFIRMED"
    assignment["confirmed_at"] = CLOCK.now_iso()
    touch(assignment)
    return success_object(public(assignment))


@bp.post("/staffing-assignments/<staffingAssignmentId>/cancel")
def cancel_staffing_assignment(staffingAssignmentId):
    authorized(["LabDirector"])
    assignment = require_path_resource("staffing_assignments", staffingAssignmentId)
    if assignment["status"] not in ("PLANNED", "CONFIRMED"):
        raise_error(ERR_STAFFING_INVALID_STATE,
                    f"cancel requires PLANNED or CONFIRMED, found {assignment['status']}")
    if assignment["status"] == "CONFIRMED":
        # Capacity guard: occupied must remain <= remaining confirmed capacity
        # after subtracting this assignment's capacity.
        date = assignment["shift_date"]
        remaining = confirmed_capacity(date) - assignment["patient_capacity"]
        if occupied_inlab(date) > remaining:
            raise_error(ERR_CAPACITY_WOULD_BE_VIOLATED,
                        "cancelling would leave scheduled in-lab studies above remaining capacity")
    assignment["status"] = "CANCELLED"
    touch(assignment)
    return success_object(public(assignment))
