"""SEVIS records: creation (1:1), listing, initialize, terminate (PRD §3.2, §3.9)."""

from flask import Blueprint

import db
import services
from db import new_id, stamp_new, touch
from errors import (
    ERR_NO_ISSUED_I20,
    ERR_RECORD_ALREADY_EXISTS,
    ERR_RECORD_NOT_ACTIVE,
    ERR_RECORD_NOT_DRAFT,
    ERR_RESOURCE_NOT_OWNED,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, req_date, req_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import sevis_record_out

bp = Blueprint("records", __name__)


@bp.route("/sevis/students/<sid>/sevis-records", methods=["POST"])
def create_sevis_record(sid):
    require_roles(STAFF_ROLES)
    student = get_student_or_404(sid)
    data = body()
    program_start_date = req_date(data, "program_start_date")
    program_end_date = req_date(data, "program_end_date")
    if services.record_of_student(student["id"]) is not None:
        raise_error(ERR_RECORD_ALREADY_EXISTS, "Student already has a SevisRecord (1:1)")
    record = {
        "id": new_id(),
        "student_id": student["id"],
        "program_start_date": program_start_date,
        "program_end_date": program_end_date,
        "status": "DRAFT",
        "termination_reason": None,
    }
    stamp_new(record)
    db.sevis_records[record["id"]] = record
    return success_object(sevis_record_out(record), 201)


@bp.route("/sevis/students/<sid>/sevis-records", methods=["GET"])
def list_sevis_records(sid):
    user_id, role = require_roles(ALL_ROLES)
    if role == "Student" and user_id != sid:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only act on their own resources")
    student = get_student_or_404(sid)
    items = [r for r in db.sevis_records.values() if r["student_id"] == student["id"]]
    return list_response(items, sevis_record_out)


@bp.route("/sevis/sevis-records/<rid>/initialize", methods=["POST"])
def initialize_record(rid):
    require_roles(STAFF_ROLES)
    record = get_or_404(db.sevis_records, rid, "SevisRecord")
    if record["status"] != "DRAFT":
        raise_error(ERR_RECORD_NOT_DRAFT, "Record must be DRAFT for initialize")
    if not services.issued_forms_of_record(record["id"]):
        raise_error(ERR_NO_ISSUED_I20, "No ISSUED I-20 exists for the record")
    record["status"] = "INITIAL"
    touch(record)
    return success_object(sevis_record_out(record), 200)


@bp.route("/sevis/sevis-records/<rid>/terminate", methods=["POST"])
def terminate_record(rid):
    require_roles(("PDSO",))
    record = get_or_404(db.sevis_records, rid, "SevisRecord")
    data = body()
    reason = req_str(data, "termination_reason")
    if record["status"] != "ACTIVE":
        raise_error(ERR_RECORD_NOT_ACTIVE, "Record must be ACTIVE to terminate")
    services.terminate_record_cascade(record)
    record["status"] = "TERMINATED"
    record["termination_reason"] = reason
    touch(record)
    services.recompute_posture(record["student_id"])
    return success_object(sevis_record_out(record), 200)
