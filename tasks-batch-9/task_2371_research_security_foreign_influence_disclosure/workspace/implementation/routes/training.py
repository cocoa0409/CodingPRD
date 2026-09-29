"""Training assignments with a purely derived status (PRD 3.9)."""

from flask import Blueprint

import db
import response
import validate
from errors import ApiError
from middleware import INVESTIGATOR, RSO, SYSTEM_ADMIN, require, require_any
from routes.common import must_exist, render_list
from services import cascade, enums as E, present

bp = Blueprint("training", __name__)


def _reconcile(record):
    cascade.recompute_investigator_by_id(record["investigator_id"])
    if record.get("required_for_project_id"):
        cascade.recompute_project_by_id(record["required_for_project_id"])


@bp.post("/training-assignments")
def create_assignment():
    require(SYSTEM_ADMIN, RSO)
    data = validate.body()

    # step 5 — body foreign keys in declaration order
    investigator = must_exist("investigator", data.get("investigator_id"))
    project = None
    if data.get("required_for_project_id") is not None:
        project = must_exist("project", data.get("required_for_project_id"))

    course_code = validate.req_enum(data, "course_code", E.COURSE_CODES)
    due_on = validate.req_instant(data, "due_on")

    record = db.base_record()
    record.update({
        "investigator_id": investigator["id"],
        "required_for_project_id": project["id"] if project else None,
        "course_code": course_code,
        "assigned_on": db.clock_str(),
        "due_on": due_on,
        "completed_on": None,
        "waived_on": None,
    })
    db.trainings[record["id"]] = record
    _reconcile(record)
    return response.object_response(present.training(record), 201)


@bp.get("/training-assignments/<assignment_id>")
def read_assignment(assignment_id):
    require_any()
    record = must_exist("training", assignment_id)
    return response.object_response(present.training(record))


@bp.get("/training-assignments")
def list_assignments():
    require_any()
    investigator_id = validate.filter_value("investigator_id")
    project_id = validate.filter_value("required_for_project_id")
    course_code = validate.filter_enum("course_code", E.COURSE_CODES)

    rows = []
    for record in db.ordered(db.trainings.values()):
        if investigator_id and record["investigator_id"] != investigator_id:
            continue
        if project_id and record["required_for_project_id"] != project_id:
            continue
        if course_code and record["course_code"] != course_code:
            continue
        rows.append(record)
    return render_list(rows, present.training)


def _guard_unresolved(record):
    if record["completed_on"] is not None or record["waived_on"] is not None:
        raise ApiError("ERR_TRAINING_ALREADY_RESOLVED",
                       "This assignment is already completed or waived.")


@bp.post("/training-assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    require(INVESTIGATOR, SYSTEM_ADMIN)
    record = must_exist("training", assignment_id)
    _guard_unresolved(record)
    record["completed_on"] = db.clock_str()
    db.touch(record)
    _reconcile(record)
    return response.object_response(present.training(record))


@bp.post("/training-assignments/<assignment_id>/waive")
def waive_assignment(assignment_id):
    require(RSO)
    record = must_exist("training", assignment_id)
    _guard_unresolved(record)
    record["waived_on"] = db.clock_str()
    db.touch(record)
    _reconcile(record)
    return response.object_response(present.training(record))
