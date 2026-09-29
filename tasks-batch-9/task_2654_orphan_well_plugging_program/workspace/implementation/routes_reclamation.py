"""Surface reclamation tasks and the closeout rollup (PRD 3.8)."""
from flask import Blueprint

import calc
import validate as v
from auth import (CONTRACTOR, DETERMINATION_REVIEWER, FIELD_INSPECTOR,
                  FUNDING_OFFICER, PROGRAM_ADMIN, endpoint, user_id)
from envelope import filter_value, object_response, paginated
from errors import ApiError
from lookup import collect, get_job, get_task, get_well
from store import clock, db, days, touch

bp = Blueprint("reclamation", __name__)

PROGRESS_ACTIONS = ("START", "PASS", "FAIL")
TASK_READERS = (PROGRAM_ADMIN, FIELD_INSPECTOR, DETERMINATION_REVIEWER,
                FUNDING_OFFICER, CONTRACTOR)


def _job_tasks(job_id):
    return [t for t in db.tasks.values() if t["job_id"] == job_id]


def _sibling(job_id, task_type):
    for task in db.tasks.values():
        if task["job_id"] == job_id and task["task_type"] == task_type:
            return task
    return None


@bp.route("/plugging-jobs/<job_id>/reclamation-tasks", methods=["GET"])
@endpoint(TASK_READERS)
def list_job_tasks(job_id):
    get_job(job_id)
    status = filter_value("status")

    def keep(row):
        if row["job_id"] != job_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(collect(db.tasks, keep, sort_key=lambda r: r["task_type"]))


@bp.route("/reclamation-tasks/<task_id>", methods=["GET"])
@endpoint(TASK_READERS)
def fetch_task(task_id):
    return object_response(get_task(task_id))


@bp.route("/reclamation-tasks/<task_id>/progress", methods=["POST"])
@endpoint((FIELD_INSPECTOR,), needs_user_id=True)
def advance_task(task_id):
    task = get_task(task_id)
    data = v.body()
    action = v.enum_field(data, "action", PROGRESS_ACTIONS)
    notes = None
    if data.get("notes") is not None:
        notes = v.str_field(data, "notes")

    job = get_job(task["job_id"])

    if action == "START":
        if task["status"] not in ("PENDING", "REWORK_NEEDED"):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "A task in %s cannot be started." % task["status"],
            )
        if job["status"] != "PLUGGED":
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Reclamation work requires a PLUGGED job.",
            )
        if task["task_type"] == "REVEGETATION":
            pit = _sibling(task["job_id"], "PIT_CLOSURE")
            ready = (
                pit is not None
                and pit["status"] == "COMPLETE"
                and pit["completed_at"] is not None
                and clock() >= pit["completed_at"] + days(calc.REVEGETATION_WAIT_DAYS)
            )
            if not ready:
                raise ApiError(
                    "ERR_REVEGETATION_WAITING_PERIOD",
                    "Revegetation may not start until %d days after pit closure."
                    % calc.REVEGETATION_WAIT_DAYS,
                )
        task["status"] = "IN_PROGRESS"
        if notes is not None:
            task["notes"] = notes
        touch(task)
        return object_response(task)

    if task["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A task in %s has no inspection to record." % task["status"],
        )

    if action == "FAIL":
        task["inspection_round"] += 1
        task["status"] = "REWORK_NEEDED"
        task["inspected_by_user_id"] = user_id()
        if notes is not None:
            task["notes"] = notes
        touch(task)
        return object_response(task)

    # action PASS
    if task["task_type"] == "REVEGETATION":
        for sibling_type in ("EQUIPMENT_REMOVAL", "PIT_CLOSURE"):
            sibling = _sibling(task["job_id"], sibling_type)
            if sibling is None or sibling["status"] != "COMPLETE":
                raise ApiError(
                    "ERR_RECLAMATION_INCOMPLETE",
                    "%s must be COMPLETE before revegetation sign-off."
                    % sibling_type,
                )

    task["status"] = "COMPLETE"
    task["completed_at"] = clock()
    task["inspected_by_user_id"] = user_id()
    if notes is not None:
        task["notes"] = notes
    touch(task)

    siblings = _job_tasks(task["job_id"])
    if (len(siblings) == 3
            and all(t["status"] == "COMPLETE" for t in siblings)
            and job["status"] == "PLUGGED"):
        job["status"] = "RECLAIMED"
        job["reclaimed_at"] = clock()
        touch(job)
        well = get_well(job["well_id"])
        if well["status"] == "PLUGGED":
            well["status"] = "RECLAIMED"
            touch(well)
            operator = db.operators.get(well["operator_id"])
            if operator is not None:
                calc.recompute_operator(operator)

    return object_response(task)
