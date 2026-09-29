"""Utility clearance rows (PRD 3.5)."""
from flask import Blueprint

import clock
import db
import response
import validators as v
from errors import ApiError
from middleware import endpoint
from services import derive

bp = Blueprint("coordinations", __name__)

RESPONSES = ("CLEAR", "CONFLICT", "SCHEDULE_WORK", "RE_REQUEST")
READ_ROLES = ("PavementEngineer", "UtilityCoordinator", "BudgetOfficer",
              "Inspector")


def _find_coordination(coordination_id):
    row = db.coordinations.get(coordination_id)
    if row is None:
        raise ApiError("ERR_COORDINATION_NOT_FOUND")
    return row


@bp.get("/utility-coordinations/<coordination_id>")
@endpoint(*READ_ROLES)
def read_coordination(coordination_id):
    return response.object_response(_find_coordination(coordination_id))


@bp.get("/utility-coordinations")
@endpoint(*READ_ROLES)
def list_coordinations():
    rows = v.filter_rows(db.ordered(db.coordinations.values()), {
        "project_id": "project_id",
        "coordination_status": "coordination_status",
        "utility": "utility",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/utility-coordinations/<coordination_id>/respond")
@endpoint("UtilityCoordinator")
def respond(coordination_id):
    data = v.body()
    answer = v.field_enum(data, "response", RESPONSES)
    note = v.field_string(data, "response_note", 1, 500, required=False)
    if answer == "SCHEDULE_WORK":
        work_start = v.field_datetime(data, "planned_work_start")
        work_end = v.field_datetime(data, "planned_work_end")
        v.window(work_start, work_end, "planned utility work window")
    else:
        work_start = work_end = None

    row = _find_coordination(coordination_id)
    project = db.projects.get(row["project_id"])

    if answer in ("CLEAR", "CONFLICT"):
        if row["coordination_status"] != "CLEARANCE_REQUESTED":
            raise ApiError("ERR_COORDINATION_NOT_PENDING")
    elif answer == "SCHEDULE_WORK":
        if row["coordination_status"] != "CONFLICT_DECLARED":
            raise ApiError("ERR_COORDINATION_NOT_IN_CONFLICT")
    else:  # RE_REQUEST
        if row["coordination_status"] != "WORK_COMPLETE":
            raise ApiError("ERR_COORDINATION_NOT_WORK_COMPLETE")

    if answer == "SCHEDULE_WORK":
        if project is not None and work_end > project["planned_start_date"]:
            raise ApiError("ERR_UTILITY_WORK_AFTER_PAVING")

    updates = {}
    if note is not None:
        updates["response_note"] = note

    if answer == "CLEAR":
        updates["coordination_status"] = \
            "CLEARED" if row["round_count"] < 2 else "CLEARED_AFTER_WORK"
    elif answer == "CONFLICT":
        updates["coordination_status"] = "CONFLICT_DECLARED"
    elif answer == "SCHEDULE_WORK":
        updates["coordination_status"] = "WORK_SCHEDULED"
        updates["planned_work_start"] = work_start
        updates["planned_work_end"] = work_end
    else:
        updates["coordination_status"] = "CLEARANCE_REQUESTED"
        updates["round_count"] = row["round_count"] + 1

    derive.apply_updates(row, updates)
    if project is not None:
        derive.recompute_project_counters(project)
    return response.object_response(row)


@bp.post("/utility-coordinations/<coordination_id>/complete-work")
@endpoint("UtilityCoordinator")
def complete_work(coordination_id):
    v.body()
    row = _find_coordination(coordination_id)
    if row["coordination_status"] != "WORK_SCHEDULED":
        raise ApiError("ERR_COORDINATION_WORK_NOT_SCHEDULED")
    derive.apply_updates(row, {
        "coordination_status": "WORK_COMPLETE",
        "work_completed_at": clock.now(),
    })
    project = db.projects.get(row["project_id"])
    if project is not None:
        derive.recompute_project_counters(project)
    return response.object_response(row)
