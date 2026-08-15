"""Scoring assignments, epoch submission, physician review (PRD 3.5)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INSUFFICIENT_REASON,
    ERR_STUDY_NOT_SCORABLE,
    ERR_SOD_PRIMARY_SCORER,
    ERR_SCORER_NOT_IN_POOL,
    ERR_SCORER_IN_REMEDIATION,
    ERR_PRIMARY_TASK_EXISTS,
    ERR_NOT_TASK_OWNER,
    ERR_TASK_NOT_STARTABLE,
    ERR_TASK_NOT_SUBMITTABLE,
    ERR_TASK_NOT_SUBMITTED,
    ERR_TASK_TERMINAL,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public, query_filters
from services.calculations import IN_LAB_TYPES, TASK_TERMINAL, compute_indexes
from services.core import new_record, touch
from util import CLOCK
from validate import (
    get_body, req_str, req_enum, req_int, opt_int, require_path_resource, require_body_ref,
)

bp = Blueprint("scoring_tasks", __name__)

ASSIGNMENT_KINDS = {"PRIMARY", "RELIABILITY_RESCORE"}
RESCORE_STUDY_STATES = {"SCORED", "INTERPRETATION_IN_PROGRESS", "INTERPRETED", "REPORT_FINALIZED"}


def _accepted_primary_task(study_id):
    for task in db["scoring_tasks"].values():
        if (task["study_id"] == study_id
                and task["assignment_kind"] == "PRIMARY"
                and task["status"] == "ACCEPTED"):
            return task
    return None


@bp.post("/scoring-tasks")
def create_scoring_task():
    authorized(["LabDirector"])
    body = get_body()
    # Priority 3: body FK existence in declaration order (study_id, scorer_id).
    study = require_body_ref("sleep_studies", body.get("study_id"))
    scorer = require_body_ref("scorers", body.get("scorer_id"))
    # Priority 4: shape.
    study_id = req_str(body, "study_id")
    scorer_id = req_str(body, "scorer_id")
    assignment_kind = req_enum(body, "assignment_kind", ASSIGNMENT_KINDS)
    # Priority 7: study scorability for the assignment kind.
    if assignment_kind == "PRIMARY":
        if study["status"] != "SCORING_QUEUED":
            raise_error(ERR_STUDY_NOT_SCORABLE,
                        "PRIMARY assignment requires study SCORING_QUEUED")
    else:
        if study["status"] not in RESCORE_STUDY_STATES:
            raise_error(ERR_STUDY_NOT_SCORABLE,
                        "RELIABILITY_RESCORE requires study SCORED or beyond")
    # Priority 8: segregation of duties — rescorer differs from the accepted
    # primary scorer.
    if assignment_kind == "RELIABILITY_RESCORE":
        primary = _accepted_primary_task(study_id)
        if primary is not None and primary["scorer_id"] == scorer_id:
            raise_error(ERR_SOD_PRIMARY_SCORER,
                        "RELIABILITY_RESCORE may not be assigned to the primary scorer")
    # Priority 9: scorer assignability.
    if not scorer["is_active"]:
        raise_error(ERR_INVALID_REQUEST, "scorer is inactive")
    if assignment_kind == "RELIABILITY_RESCORE" and not scorer["reliability_pool"]:
        raise_error(ERR_SCORER_NOT_IN_POOL,
                    "RELIABILITY_RESCORE requires a reliability_pool scorer")
    if scorer["reliability_status"] == "REMEDIATION":
        raise_error(ERR_SCORER_IN_REMEDIATION,
                    "scorer in REMEDIATION may not receive new assignments")
    # Priority 11: one non-terminal PRIMARY task per study.
    if assignment_kind == "PRIMARY":
        for task in db["scoring_tasks"].values():
            if (task["study_id"] == study_id
                    and task["assignment_kind"] == "PRIMARY"
                    and task["status"] not in TASK_TERMINAL):
                raise_error(ERR_PRIMARY_TASK_EXISTS,
                            "a non-terminal PRIMARY ScoringTask already exists for the study")
    rec = new_record("scoring_tasks", {
        "study_id": study_id,
        "scorer_id": scorer_id,
        "assignment_kind": assignment_kind,
        "obstructive_apneas": None,
        "central_apneas": None,
        "mixed_apneas": None,
        "hypopneas": None,
        "reras": None,
        "epochs_total": None,
        "total_sleep_time_minutes": None,
        "total_recording_time_minutes": None,
        "ahi": None,
        "rdi": None,
        "rei": None,
        "submitted_at": None,
        "returned_reason": None,
        "status": "ASSIGNED",
    })
    return success_object(public(rec), status=201)


@bp.get("/scoring-tasks")
def list_scoring_tasks():
    return list_response("scoring_tasks", query_filters("study_id", "scorer_id", "status"))


@bp.get("/scoring-tasks/<scoringTaskId>")
def get_scoring_task(scoringTaskId):
    return get_one("scoring_tasks", scoringTaskId)


def _check_owner(caller, task):
    if caller.user_id != task["scorer_id"]:
        raise_error(ERR_NOT_TASK_OWNER, "X-User-ID must equal the task's scorer_id")


@bp.post("/scoring-tasks/<scoringTaskId>/start")
def start_task(scoringTaskId):
    caller = authorized(["Scorer"])
    task = require_path_resource("scoring_tasks", scoringTaskId)
    _check_owner(caller, task)
    if task["status"] in TASK_TERMINAL:
        raise_error(ERR_TASK_TERMINAL, f"task is terminal ({task['status']})")
    if task["status"] not in ("ASSIGNED", "RETURNED_FOR_REVISION"):
        raise_error(ERR_TASK_NOT_STARTABLE,
                    f"start requires ASSIGNED or RETURNED_FOR_REVISION, found {task['status']}")
    task["status"] = "IN_PROGRESS"
    touch(task)
    if task["assignment_kind"] == "PRIMARY":
        study = db["sleep_studies"].get(task["study_id"])
        if study is not None and study["status"] == "SCORING_QUEUED":
            study["status"] = "SCORING_IN_PROGRESS"
            touch(study)
    return success_object(public(task))


@bp.post("/scoring-tasks/<scoringTaskId>/submit")
def submit_task(scoringTaskId):
    caller = authorized(["Scorer"])
    task = require_path_resource("scoring_tasks", scoringTaskId)
    study = db["sleep_studies"].get(task["study_id"])
    body = get_body()
    # Priority 4: shape — event counts, epoch total, and the per-type time base.
    obstructive = req_int(body, "obstructive_apneas", non_negative=True)
    central = req_int(body, "central_apneas", non_negative=True)
    mixed = req_int(body, "mixed_apneas", non_negative=True)
    hypopneas = req_int(body, "hypopneas", non_negative=True)
    reras = req_int(body, "reras", non_negative=True)
    epochs_total = req_int(body, "epochs_total", positive=True)
    study_type = study["study_type"] if study is not None else None
    if study_type == "HST":
        if body.get("total_sleep_time_minutes") is not None:
            raise_error(ERR_INVALID_REQUEST,
                        "total_sleep_time_minutes must be omitted for HST")
        tst = None
        trt = req_int(body, "total_recording_time_minutes", positive=True)
    else:
        tst = req_int(body, "total_sleep_time_minutes", positive=True)
        trt = opt_int(body, "total_recording_time_minutes", None, positive=True)
        if trt is not None and trt < tst:
            raise_error(ERR_INVALID_REQUEST,
                        "total_recording_time_minutes must be >= total_sleep_time_minutes")
    # Priority 5: ownership.
    _check_owner(caller, task)
    # Priority 7: state (terminal guard fires ahead of the submittable check).
    if task["status"] in TASK_TERMINAL:
        raise_error(ERR_TASK_TERMINAL, f"task is terminal ({task['status']})")
    if task["status"] != "IN_PROGRESS":
        raise_error(ERR_TASK_NOT_SUBMITTABLE,
                    f"submit requires IN_PROGRESS, found {task['status']}")
    ahi, rdi, rei = compute_indexes(study_type, obstructive, central, mixed,
                                    hypopneas, reras, tst, trt)
    task["obstructive_apneas"] = obstructive
    task["central_apneas"] = central
    task["mixed_apneas"] = mixed
    task["hypopneas"] = hypopneas
    task["reras"] = reras
    task["epochs_total"] = epochs_total
    task["total_sleep_time_minutes"] = tst
    task["total_recording_time_minutes"] = trt
    task["ahi"] = ahi
    task["rdi"] = rdi
    task["rei"] = rei
    task["submitted_at"] = CLOCK.now_iso()
    task["status"] = "SUBMITTED"
    touch(task)
    return success_object(public(task))


@bp.post("/scoring-tasks/<scoringTaskId>/accept")
def accept_task(scoringTaskId):
    authorized(["InterpretingPhysician"])
    task = require_path_resource("scoring_tasks", scoringTaskId)
    if task["status"] in TASK_TERMINAL:
        raise_error(ERR_TASK_TERMINAL, f"task is terminal ({task['status']})")
    if task["status"] != "SUBMITTED":
        raise_error(ERR_TASK_NOT_SUBMITTED,
                    f"accept requires SUBMITTED, found {task['status']}")
    task["status"] = "ACCEPTED"
    touch(task)
    if task["assignment_kind"] == "PRIMARY":
        study = db["sleep_studies"].get(task["study_id"])
        if study is not None and study["status"] == "SCORING_IN_PROGRESS":
            study["accepted_ahi"] = task["ahi"]
            study["accepted_rdi"] = task["rdi"]
            study["accepted_rei"] = task["rei"]
            study["status"] = "SCORED"
            touch(study)
    return success_object(public(task))


@bp.post("/scoring-tasks/<scoringTaskId>/return")
def return_task(scoringTaskId):
    authorized(["InterpretingPhysician"])
    task = require_path_resource("scoring_tasks", scoringTaskId)
    body = get_body()
    reason = req_str(body, "reason")
    if len(reason) < 10:
        raise_error(ERR_INSUFFICIENT_REASON, "return reason shorter than 10 characters")
    if task["status"] in TASK_TERMINAL:
        raise_error(ERR_TASK_TERMINAL, f"task is terminal ({task['status']})")
    if task["status"] != "SUBMITTED":
        raise_error(ERR_TASK_NOT_SUBMITTED,
                    f"return requires SUBMITTED, found {task['status']}")
    task["status"] = "RETURNED_FOR_REVISION"
    task["returned_reason"] = reason
    touch(task)
    return success_object(public(task))
