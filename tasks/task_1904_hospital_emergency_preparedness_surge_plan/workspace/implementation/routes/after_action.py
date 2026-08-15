"""After-action reports and improvement tasks."""

from flask import Blueprint, g, request

from db import clock, store
from domain import (DEPARTMENTS, SUBJECT_TYPES, TASK_PRIORITIES, TASK_STATUSES,
                    get_or_404, list_response, ser_aar, ser_task)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import (field_dt, field_enum, field_str, new_entity, require_body, touch)

bp = Blueprint("after_action", __name__)


@bp.post("/after-action-reports")
@authorize(["EmergencyManager", "IncidentCommander"])
def create_aar():
    body = require_body()
    subject_type = field_enum(body, "subject_type", SUBJECT_TYPES, required=True)
    subject_id = field_str(body, "subject_id", required=True)
    summary = field_str(body, "summary", required=True)

    if subject_type == "EXERCISE":
        subject = get_or_404("exercises", subject_id)
        if subject["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "an exercise AAR requires a COMPLETED exercise")
    else:
        subject = get_or_404("incidents", subject_id)
        if subject["status"] != "DEACTIVATED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "an incident AAR requires a DEACTIVATED incident")

    for other in store["after_action_reports"].values():
        if other["subject_type"] == subject_type and other["subject_id"] == subject_id:
            raise ApiError("ERR_AAR_ALREADY_EXISTS", 409,
                           "an after-action report already exists for this subject")

    aar = new_entity()
    aar.update({
        "subject_type": subject_type,
        "subject_id": subject_id,
        "summary": summary,
        "status": "DRAFT",
        "created_by_id": g.user_id,
        "submitted_at": None,
        "approved_by_id": None,
        "approved_at": None,
    })
    store["after_action_reports"][aar["id"]] = aar
    return success(ser_aar(aar), "object", 201)


@bp.get("/after-action-reports/<aar_id>")
@authorize(ALL_ROLES)
def get_aar(aar_id):
    return success(ser_aar(get_or_404("after_action_reports", aar_id)), "object", 200)


@bp.post("/after-action-reports/<aar_id>/submit")
@authorize(["EmergencyManager", "IncidentCommander"])
def submit_aar(aar_id):
    aar = get_or_404("after_action_reports", aar_id)
    if aar["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "only a DRAFT report can be submitted")
    aar["status"] = "SUBMITTED"
    aar["submitted_at"] = clock.now()
    touch(aar)
    return success(ser_aar(aar), "object", 200)


@bp.post("/after-action-reports/<aar_id>/approve")
@authorize(["HospitalAdministrator"])
def approve_aar(aar_id):
    aar = get_or_404("after_action_reports", aar_id)
    # Segregation of duties (priority 6) precedes the state guard (priority 8).
    if g.user_id == aar["created_by_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "the approver may not be the report's creator")
    if aar["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SUBMITTED report can be approved")
    aar["status"] = "APPROVED"
    aar["approved_by_id"] = g.user_id
    aar["approved_at"] = clock.now()
    touch(aar)
    return success(ser_aar(aar), "object", 200)


# ---------------------------------------------------------------------------
# Improvement tasks
# ---------------------------------------------------------------------------

_TASK_TRANSITIONS = {
    "OPEN": {"IN_PROGRESS"},
    "OVERDUE": {"IN_PROGRESS"},
    "IN_PROGRESS": {"VERIFIED_COMPLETE"},
    "VERIFIED_COMPLETE": set(),
}


@bp.post("/improvement-tasks")
@authorize(["EmergencyManager"])
def create_task():
    body = require_body()
    aar_id = field_str(body, "after_action_report_id", required=True)
    description = field_str(body, "description", required=True)
    priority = field_enum(body, "priority", TASK_PRIORITIES, required=True)
    due_date = field_dt(body, "due_date", required=True)
    assigned_department = field_enum(body, "assigned_department", DEPARTMENTS,
                                     required=True)

    aar = get_or_404("after_action_reports", aar_id)
    if aar["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "tasks may be added only while the report is DRAFT or SUBMITTED")

    task = new_entity()
    task.update({
        "after_action_report_id": aar_id,
        "description": description,
        "priority": priority,
        "due_date": due_date,
        "assigned_department": assigned_department,
        "status": "OPEN",
    })
    store["improvement_tasks"][task["id"]] = task
    return success(ser_task(task), "object", 201)


@bp.get("/improvement-tasks")
@authorize(ALL_ROLES)
def list_tasks():
    aar_id = request.args.get("after_action_report_id")
    status = request.args.get("status")

    def predicate(t):
        if aar_id is not None and t["after_action_report_id"] != aar_id:
            return False
        if status is not None and t["status"] != status:
            return False
        return True

    return list_response("improvement_tasks", ser_task, predicate)


@bp.get("/improvement-tasks/<task_id>")
@authorize(ALL_ROLES)
def get_task(task_id):
    return success(ser_task(get_or_404("improvement_tasks", task_id)), "object", 200)


@bp.patch("/improvement-tasks/<task_id>")
@authorize(["EmergencyManager"])
def patch_task(task_id):
    task = get_or_404("improvement_tasks", task_id)
    body = require_body()
    target_status = field_enum(body, "target_status", TASK_STATUSES, required=True)

    if target_status not in _TASK_TRANSITIONS[task["status"]]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "cannot move a %s task to %s" % (task["status"], target_status))
    task["status"] = target_status
    touch(task)
    return success(ser_task(task), "object", 200)
