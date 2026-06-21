"""Household endpoints and the student rule (PRD §3.2)."""

from flask import Blueprint, request

import errors
import middleware
import response
import serializers
import validate
from db import db, new_id, stamp_create

bp = Blueprint("households", __name__)

STUDENT_EXCEPTIONS = {
    "NONE", "TANF", "JOB_TRAINING", "SINGLE_PARENT", "MARRIED_JOINT_FILER", "FORMER_FOSTER"
}


@bp.route("/households", methods=["POST"])
def create_household():
    middleware.require_role("OwnerAgent")
    body = validate.get_json_body()
    project_id = validate.as_str(body, "project_id")
    head_name = validate.as_str(body, "head_name")
    household_size = validate.as_int(body, "household_size", minimum=1)
    all_students = validate.as_bool(body, "all_full_time_students")
    student_exception = validate.as_enum(
        body, "student_exception", STUDENT_EXCEPTIONS, required=False, default="NONE"
    )

    if db.projects.get(project_id) is None:
        raise errors.not_found("Project not found")

    student_eligible = not (all_students and student_exception == "NONE")

    household = {
        "id": new_id(),
        "project_id": project_id,
        "head_name": head_name,
        "household_size": household_size,
        "all_full_time_students": all_students,
        "student_exception": student_exception,
        "student_eligible": student_eligible,
    }
    stamp_create(household)
    db.households[household["id"]] = household
    return response.success(serializers.public(household), status=201)


@bp.route("/households", methods=["GET"])
def list_households():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    project_id = request.args.get("project_id")
    items = list(db.households.values())
    if project_id is not None:
        items = [h for h in items if h["project_id"] == project_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    middleware.require_role("OwnerAgent", "StateHFA")
    household = db.households.get(hid)
    if household is None:
        raise errors.not_found("Household not found")
    return response.success(serializers.public(household), status=200)
