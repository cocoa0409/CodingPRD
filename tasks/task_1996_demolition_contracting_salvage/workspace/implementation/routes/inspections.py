"""FinalInspection endpoints: scheduling (one SCHEDULED at a time), PASS with
the closure compliance gates, FAIL/RESCHEDULE re-inspection cycle."""

from flask import Blueprint

from db import store, now, new_record, touch
from errors import (err, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_BACKFILL_INCOMPLETE, ERR_DIVERSION_BELOW_REQUIREMENT,
                    ERR_INSPECTION_OUTSTANDING)
from middleware import require_roles, body
from response import success, list_response
from serializers import ser_final_inspection
from services import (get_project, get_final_inspection, children,
                      project_inspections, project_backfill_plans)
from util import req_enum, req_date_str, opt_str

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("FINAL_LOT", "EROSION_CLOSEOUT")
INSPECTION_READ_ROLES = ("ContractorAdmin", "SiteSupervisor", "MunicipalInspector")
INSPECTION_ACTIONS = ("PASS", "FAIL", "RESCHEDULE")


@bp.post("/demolition/projects/<pid>/final-inspections")
@require_roles("MunicipalInspector")
def create_inspection(pid):
    b = body()
    inspection_type = req_enum(b, "inspection_type", INSPECTION_TYPES)
    scheduled_date = req_date_str(b, "scheduled_date")
    project = get_project(pid)
    if project["status"] != "FINAL_REVIEW":
        raise err(ERR_INVALID_STATE, "final inspections require FINAL_REVIEW")
    if any(i["status"] == "SCHEDULED" for i in project_inspections(project["id"])):
        raise err(ERR_INSPECTION_OUTSTANDING, "another inspection is already SCHEDULED")

    rec = new_record()
    rec.update({
        "project_id": project["id"],
        "inspection_type": inspection_type,
        "scheduled_date": scheduled_date,
        "status": "SCHEDULED",
        "attempt_count": 0,
        "inspector_note": "",
        "passed_at": None,
    })
    store.final_inspections[rec["id"]] = rec
    return success(ser_final_inspection(rec), status=201)


@bp.get("/demolition/projects/<pid>/final-inspections")
@require_roles(*INSPECTION_READ_ROLES)
def list_inspections(pid):
    project = get_project(pid)
    return list_response(project_inspections(project["id"]), ser_final_inspection)


@bp.post("/demolition/final-inspections/<iid>/transition")
@require_roles("MunicipalInspector")
def inspection_transition(iid):
    b = body()
    action = b.get("action")
    if not isinstance(action, str) or action not in INSPECTION_ACTIONS:
        raise err(ERR_VALIDATION, "invalid action")
    note = opt_str(b, "inspector_note")
    new_date = None
    if "scheduled_date" in b and b["scheduled_date"] is not None:
        new_date = req_date_str(b, "scheduled_date")

    insp = get_final_inspection(iid)
    project = store.projects[insp["project_id"]]

    if action == "PASS":
        if insp["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "PASS requires SCHEDULED")
        if project["status"] != "FINAL_REVIEW":
            raise err(ERR_INVALID_STATE, "project is not in FINAL_REVIEW")
        if not any(bp_["status"] == "COMPLETE" for bp_ in project_backfill_plans(project["id"])):
            raise err(ERR_BACKFILL_INCOMPLETE, "no COMPLETE backfill plan")
        if project["diversion_rate"] < project["required_diversion_rate"]:
            raise err(ERR_DIVERSION_BELOW_REQUIREMENT, "diversion rate below requirement")
        insp["status"] = "PASSED"
        insp["passed_at"] = now()
        if note is not None:
            insp["inspector_note"] = note
        touch(insp)
        # Closure cascade: FINAL_REVIEW -> CLOSED.
        project["status"] = "CLOSED"
        touch(project)
    elif action == "FAIL":
        if insp["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "FAIL requires SCHEDULED")
        insp["status"] = "FAILED"
        insp["attempt_count"] += 1
        if note is not None:
            insp["inspector_note"] = note
        touch(insp)
    else:  # RESCHEDULE
        if insp["status"] != "FAILED":
            raise err(ERR_INVALID_STATE, "RESCHEDULE requires FAILED")
        if new_date is None:
            raise err(ERR_VALIDATION, "scheduled_date is required")
        insp["scheduled_date"] = new_date
        insp["status"] = "SCHEDULED"
        if note is not None:
            insp["inspector_note"] = note
        touch(insp)

    return success(ser_final_inspection(insp))
