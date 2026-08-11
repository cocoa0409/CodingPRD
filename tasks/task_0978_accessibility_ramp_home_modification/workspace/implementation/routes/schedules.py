"""Reassessment schedule endpoints."""
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    req_enum, req_dt, opt_enum, iso,
)

bp = Blueprint("schedules", __name__)

TRIGGER_EVENTS = ("POST_INSTALL", "TIME_BASED", "CONDITION_CHANGE", "REQUEST")
PRIORITIES = ("ROUTINE", "URGENT", "EMERGENT")


def _get_schedule(case_id, schedule_id):
    case = get_case_or_404(case_id)
    rec = get_child_or_404("reassessment_schedules", schedule_id, "case_id",
                           case_id, "ERR_SCHEDULE_NOT_FOUND",
                           "Reassessment schedule")
    return case, rec


@bp.route("/cases/<caseId>/reassessment-schedules", methods=["POST"])
def create_schedule(caseId):
    require_roles("IntakeCoordinator", "ProjectManager")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    due = req_dt(b, "due_date")
    rec = new_record()
    rec.update({
        "case_id": caseId,
        "trigger_event": req_enum(b, "trigger_event", TRIGGER_EVENTS),
        "due_date": iso(due),
        "status": "PENDING",
        "linked_assessment_id": None,
        "priority": opt_enum(b, "priority", PRIORITIES, "ROUTINE"),
        "auto_generated": False,
        "_due_date_dt": due,
    })
    db["reassessment_schedules"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/reassessment-schedules", methods=["GET"])
def list_schedules(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [s for s in db["reassessment_schedules"].values()
               if s["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/reassessment-schedules/<scheduleId>", methods=["GET"])
def get_schedule(caseId, scheduleId):
    require_roles()
    _case, rec = _get_schedule(caseId, scheduleId)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/reassessment-schedules/<scheduleId>/schedule",
          methods=["POST"])
def schedule_schedule(caseId, scheduleId):
    require_roles("IntakeCoordinator")
    case, rec = _get_schedule(caseId, scheduleId)
    require_case_active(case)
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Schedule must be PENDING to schedule")
    rec["status"] = "SCHEDULED"
    touch(rec)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/reassessment-schedules/<scheduleId>/waive",
          methods=["POST"])
def waive_schedule(caseId, scheduleId):
    require_roles("ProjectManager")
    case, rec = _get_schedule(caseId, scheduleId)
    require_case_active(case)
    if rec["status"] not in ("PENDING", "SCHEDULED", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Schedule cannot be waived from its current state")
    rec["status"] = "WAIVED"
    touch(rec)
    return ok_object(serialize(rec))
