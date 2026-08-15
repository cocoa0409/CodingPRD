"""Exercise / drill endpoints."""

from flask import Blueprint, request

from db import clock, store
from domain import (EXERCISE_TYPES, HAZARD_CATEGORIES, get_or_404, list_response,
                    ser_exercise)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_dt, field_enum, field_str, new_entity, require_body, touch

bp = Blueprint("exercises", __name__)


@bp.post("/exercises")
@authorize(["EmergencyManager"])
def create_exercise():
    body = require_body()
    exercise_name = field_str(body, "exercise_name", required=True)
    exercise_type = field_enum(body, "exercise_type", EXERCISE_TYPES, required=True)
    scenario_category = field_enum(body, "scenario_category", HAZARD_CATEGORIES,
                                   required=True)
    scheduled_start = field_dt(body, "scheduled_start", required=True)
    scheduled_end = field_dt(body, "scheduled_end", required=True)
    plan_revision_id = field_str(body, "plan_revision_id", required=True)

    get_or_404("plan_revisions", plan_revision_id)

    if not scheduled_end > scheduled_start:
        raise ApiError("ERR_INVALID_TIME_RANGE", 422,
                       "scheduled_end must be strictly after scheduled_start")

    # Half-open [start, end) overlap vs exercises in SCHEDULED or IN_PROGRESS;
    # adjacency (end == start) is permitted.
    for other in store["exercises"].values():
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if scheduled_start < other["scheduled_end"] and scheduled_end > other["scheduled_start"]:
            raise ApiError("ERR_EXERCISE_TIME_CONFLICT", 409,
                           "exercise window overlaps an existing scheduled exercise")

    exercise = new_entity()
    exercise.update({
        "exercise_name": exercise_name,
        "exercise_type": exercise_type,
        "scenario_category": scenario_category,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "plan_revision_id": plan_revision_id,
        "status": "SCHEDULED",
        "started_at": None,
        "completed_at": None,
    })
    store["exercises"][exercise["id"]] = exercise
    return success(ser_exercise(exercise), "object", 201)


@bp.get("/exercises")
@authorize(ALL_ROLES)
def list_exercises():
    plan_revision_id = request.args.get("plan_revision_id")
    status = request.args.get("status")
    exercise_type = request.args.get("exercise_type")

    def predicate(e):
        if plan_revision_id is not None and e["plan_revision_id"] != plan_revision_id:
            return False
        if status is not None and e["status"] != status:
            return False
        if exercise_type is not None and e["exercise_type"] != exercise_type:
            return False
        return True

    return list_response("exercises", ser_exercise, predicate)


@bp.get("/exercises/<exercise_id>")
@authorize(ALL_ROLES)
def get_exercise(exercise_id):
    return success(ser_exercise(get_or_404("exercises", exercise_id)), "object", 200)


@bp.post("/exercises/<exercise_id>/start")
@authorize(["EmergencyManager"])
def start_exercise(exercise_id):
    exercise = get_or_404("exercises", exercise_id)
    if exercise["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SCHEDULED exercise can be started")
    plan = store["plan_revisions"].get(exercise["plan_revision_id"])
    if plan is None or plan["status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 422,
                       "the referenced plan revision is not APPROVED")
    exercise["status"] = "IN_PROGRESS"
    exercise["started_at"] = clock.now()
    touch(exercise)
    return success(ser_exercise(exercise), "object", 200)


@bp.post("/exercises/<exercise_id>/complete")
@authorize(["EmergencyManager"])
def complete_exercise(exercise_id):
    exercise = get_or_404("exercises", exercise_id)
    if exercise["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an IN_PROGRESS exercise can be completed")
    exercise["status"] = "COMPLETED"
    exercise["completed_at"] = clock.now()
    touch(exercise)
    return success(ser_exercise(exercise), "object", 200)


@bp.post("/exercises/<exercise_id>/cancel")
@authorize(["EmergencyManager"])
def cancel_exercise(exercise_id):
    exercise = get_or_404("exercises", exercise_id)
    if exercise["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SCHEDULED exercise can be cancelled")
    exercise["status"] = "CANCELLED"
    touch(exercise)
    return success(ser_exercise(exercise), "object", 200)
