"""EmployeeExposures: report / serologies / record-draw / mark-lost-to-followup."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_BASELINE_WINDOW_MISSED,
    ERR_DRAW_OUTSIDE_WINDOW,
    ERR_EMPLOYEE_NOT_FOUND,
    ERR_EXPOSURE_INVALID_STAGE,
    ERR_EXPOSURE_NOT_FOUND,
    ERR_EXPOSURE_NOT_OVERDUE,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import new_entity, touch
from services.serializers import exposure_view
from util import clock
from validate import body, pagination_args, req_dt, req_enum, req_string

bp = Blueprint("exposures", __name__)

EXPOSURE_TYPES = {"PERCUTANEOUS", "MUCOUS_MEMBRANE", "SKIN"}
SEROSTATUSES = {"UNKNOWN", "NEGATIVE", "POSITIVE"}
STAGES = ("BASELINE", "WEEK_6", "WEEK_12", "WEEK_24")
STAGE_DUE_OFFSET = {
    "BASELINE": timedelta(hours=72),
    "WEEK_6": timedelta(days=42),
    "WEEK_12": timedelta(days=84),
    "WEEK_24": timedelta(days=168),
}
FOLLOWUP_WINDOW_EARLY = timedelta(days=7)
FOLLOWUP_WINDOW_LATE = timedelta(days=28)
LOST_AFTER_OVERDUE = timedelta(days=28)


def _next_stage(e):
    recorded = {s["stage"] for s in e["recorded_stages"]}
    for st in STAGES:
        if st not in recorded:
            return st
    return None


def _due_for(e, stage):
    return e["occurred_at"] + STAGE_DUE_OFFSET[stage]


@bp.post("/api/employee-exposures")
def create_exposure():
    require_roles(["EmployeeHealthNurse"])
    b = body()
    for f in ("employee_id", "exposure_type", "occurred_at", "source_hbv_status", "source_hcv_status", "source_hiv_status"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    employee_id = b.get("employee_id")
    if not isinstance(employee_id, str) or not employee_id:
        raise_err(ERR_INVALID_REQUEST, "employee_id must be a string")
    source_patient_id = b.get("source_patient_id")
    if source_patient_id is not None and (not isinstance(source_patient_id, str) or not source_patient_id):
        raise_err(ERR_INVALID_REQUEST, "source_patient_id must be a string or null")
    exposure_type = req_enum(b, "exposure_type", EXPOSURE_TYPES)
    occurred_at = req_dt(b, "occurred_at")
    hbv = req_enum(b, "source_hbv_status", SEROSTATUSES)
    hcv = req_enum(b, "source_hcv_status", SEROSTATUSES)
    hiv = req_enum(b, "source_hiv_status", SEROSTATUSES)

    emp = db.employees.get(employee_id)
    if emp is None:
        raise_err(ERR_EMPLOYEE_NOT_FOUND, "employee id does not exist")
    if source_patient_id is not None and source_patient_id not in db.patients:
        raise_err(ERR_PATIENT_NOT_FOUND, "source patient id does not exist")

    e = new_entity({
        "employee_id": employee_id,
        "source_patient_id": source_patient_id,
        "exposure_type": exposure_type,
        "occurred_at": occurred_at,
        "source_hbv_status": hbv,
        "source_hcv_status": hcv,
        "source_hiv_status": hiv,
        "recorded_stages": [],
        "next_draw_due_at": occurred_at + STAGE_DUE_OFFSET["BASELINE"],
        "status": "REPORTED",
    })
    db.employee_exposures[e["id"]] = e
    return success_object(exposure_view(e), 201)


@bp.get("/api/employee-exposures")
def list_exposures():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    source_patient_id = request.args.get("source_patient_id")

    def _match(e):
        if employee_id is not None and e["employee_id"] != employee_id:
            return False
        if status is not None and e["status"] != status:
            return False
        if source_patient_id is not None and e["source_patient_id"] != source_patient_id:
            return False
        return True

    items = [e for e in db.employee_exposures.values() if _match(e)]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([exposure_view(e) for e in page], total, limit, offset)


@bp.get("/api/employee-exposures/<eid>")
def get_exposure(eid):
    require_roles(ALL_ROLES)
    e = db.employee_exposures.get(eid)
    if e is None:
        raise_err(ERR_EXPOSURE_NOT_FOUND, "employee exposure id does not exist")
    return success_object(exposure_view(e))


@bp.post("/api/employee-exposures/<eid>/record-source-serologies")
def record_serologies(eid):
    require_roles(["EmployeeHealthNurse"])
    b = body()
    for f in ("source_hbv_status", "source_hcv_status", "source_hiv_status"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    hbv = req_enum(b, "source_hbv_status", SEROSTATUSES)
    hcv = req_enum(b, "source_hcv_status", SEROSTATUSES)
    hiv = req_enum(b, "source_hiv_status", SEROSTATUSES)

    e = db.employee_exposures.get(eid)
    if e is None:
        raise_err(ERR_EXPOSURE_NOT_FOUND, "employee exposure id does not exist")
    if e["status"] != "REPORTED":
        raise_err(ERR_EXPOSURE_INVALID_STAGE, "record-source-serologies requires status REPORTED")

    e["source_hbv_status"] = hbv
    e["source_hcv_status"] = hcv
    e["source_hiv_status"] = hiv
    e["status"] = "SOURCE_EVALUATED"
    touch(e)
    return success_object(exposure_view(e))


@bp.post("/api/employee-exposures/<eid>/record-draw")
def record_draw(eid):
    require_roles(["EmployeeHealthNurse"])
    b = body()
    for f in ("stage", "drawn_at", "result"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    stage = req_enum(b, "stage", set(STAGES))
    drawn_at = req_dt(b, "drawn_at")
    result = req_string(b, "result")

    e = db.employee_exposures.get(eid)
    if e is None:
        raise_err(ERR_EXPOSURE_NOT_FOUND, "employee exposure id does not exist")

    if stage == "BASELINE":
        if e["status"] != "SOURCE_EVALUATED":
            raise_err(ERR_EXPOSURE_INVALID_STAGE, "baseline draw requires status SOURCE_EVALUATED")
        due = _due_for(e, "BASELINE")
        if drawn_at > due:
            raise_err(ERR_BASELINE_WINDOW_MISSED, "baseline draw drawn_at after occurred_at + 72h")
        e["recorded_stages"].append({"stage": "BASELINE", "drawn_at": drawn_at, "result": result})
        # Auto-advance BASELINE_COMPLETE -> FOLLOWUP_IN_PROGRESS
        e["status"] = "FOLLOWUP_IN_PROGRESS"
        e["next_draw_due_at"] = _due_for(e, "WEEK_6")
        touch(e)
        return success_object(exposure_view(e))

    # Follow-up stages
    if e["status"] != "FOLLOWUP_IN_PROGRESS":
        raise_err(ERR_EXPOSURE_INVALID_STAGE, "follow-up draw requires status FOLLOWUP_IN_PROGRESS")
    expected = _next_stage(e)
    if stage != expected:
        raise_err(ERR_EXPOSURE_INVALID_STAGE, f"stage must equal the next unrecorded stage ({expected})")
    due = _due_for(e, stage)
    if drawn_at < due - FOLLOWUP_WINDOW_EARLY or drawn_at > due + FOLLOWUP_WINDOW_LATE:
        raise_err(ERR_DRAW_OUTSIDE_WINDOW, "drawn_at outside [due - 7d, due + 28d] for its stage")

    e["recorded_stages"].append({"stage": stage, "drawn_at": drawn_at, "result": result})
    if stage == "WEEK_24":
        e["status"] = "COMPLETED"
        e["next_draw_due_at"] = None
    else:
        nxt = _next_stage(e)
        e["next_draw_due_at"] = _due_for(e, nxt) if nxt else None
    touch(e)
    return success_object(exposure_view(e))


@bp.post("/api/employee-exposures/<eid>/mark-lost-to-followup")
def mark_lost(eid):
    require_roles(["EmployeeHealthNurse"])
    e = db.employee_exposures.get(eid)
    if e is None:
        raise_err(ERR_EXPOSURE_NOT_FOUND, "employee exposure id does not exist")
    if e["status"] != "FOLLOWUP_IN_PROGRESS":
        raise_err(ERR_EXPOSURE_INVALID_STAGE, "mark-lost-to-followup requires status FOLLOWUP_IN_PROGRESS")
    now = clock.get()
    if e["next_draw_due_at"] is None or not (now > e["next_draw_due_at"] + LOST_AFTER_OVERDUE):
        raise_err(ERR_EXPOSURE_NOT_OVERDUE, "logical clock must be later than next_draw_due_at + 28 days")
    e["status"] = "LOST_TO_FOLLOWUP"
    e["next_draw_due_at"] = None
    touch(e)
    return success_object(exposure_view(e))
