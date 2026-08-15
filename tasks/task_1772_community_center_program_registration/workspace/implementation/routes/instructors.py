"""Instructor endpoints (PRD 3.1)."""
from flask import Blueprint

import store
from auth import ALL_ROLES, authenticate, authorize
from util import body_json, get_or_404, new_record, req_str, serialize, success_object

bp = Blueprint("instructors", __name__)

FIELDS = ["id", "full_name", "email", "created_at", "updated_at", "version"]


def instructor_out(rec):
    return serialize(rec, FIELDS)


@bp.route("/instructors", methods=["POST"])
def create_instructor():
    _, role = authenticate()
    authorize(role, ["ProgramCoordinator"])
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    rec = new_record()
    rec.update(full_name=full_name, email=email)
    store.instructors[rec["id"]] = rec
    return success_object(instructor_out(rec), 201)


@bp.route("/instructors/<instructor_id>", methods=["GET"])
def get_instructor(instructor_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.instructors, instructor_id, "Instructor")
    return success_object(instructor_out(rec), 200)
