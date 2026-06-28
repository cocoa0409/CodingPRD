"""Classroom endpoints + classroom-scoped staff-assignment list + promote-waitlist.

PRD §3.1, §3.4, §3.5, §3.10; SCAFFOLD §1.5.
"""
from flask import Blueprint

import errors
from db import db, new_common_fields, touch
from middleware import get_auth, require_role
from response import object_response, array_response
from services import compliance
from services.common import (
    get_json_body, require_fields, require_non_empty_string, require_int,
    require_enum, optional_enum, parse_pagination, sort_created_asc, paginate,
    serialize, serialize_list, str_arg,
)

bp = Blueprint("classrooms", __name__)

LEVELS = {"TODDLER", "PRIMARY", "ELEMENTARY"}
COMPLIANCE_STATUSES = {"COMPLIANT", "OVER_RATIO", "OVER_CAPACITY"}
READ_ROLES = {"Registrar", "Guide", "ComplianceOfficer", "Parent"}
STAFF_STATUSES = {"ACTIVE", "ENDED"}


@bp.route("/classrooms", methods=["POST"])
def create_classroom():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    body = get_json_body()
    require_fields(body, ["name", "level", "capacity", "min_age_months", "max_age_months"])

    name = require_non_empty_string(body, "name")
    level = require_enum(body, "level", LEVELS)
    capacity = require_int(body, "capacity", minimum=1)
    min_age = require_int(body, "min_age_months", minimum=0)
    max_age = require_int(body, "max_age_months", minimum=0)
    if max_age < min_age:
        raise errors.invalid_request("max_age_months must be >= min_age_months.")

    classroom = new_common_fields()
    classroom.update({
        "name": name,
        "level": level,
        "capacity": capacity,
        "min_age_months": min_age,
        "max_age_months": max_age,
        "placed_count": 0,
        "assigned_staff_count": 0,
        "compliance_status": "COMPLIANT",
    })
    db.classrooms[classroom["id"]] = classroom
    return object_response(serialize(classroom), 201)


@bp.route("/classrooms/<classroom_id>", methods=["GET"])
def get_classroom(classroom_id):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    classroom = db.classrooms.get(classroom_id)
    if classroom is None:
        raise errors.not_found("Classroom not found.")
    return object_response(serialize(classroom), 200)


@bp.route("/classrooms", methods=["GET"])
def list_classrooms():
    _, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    level = optional_enum(str_arg("level"), LEVELS, "level")
    comp = optional_enum(str_arg("compliance_status"), COMPLIANCE_STATUSES, "compliance_status")

    records = list(db.classrooms.values())
    if level is not None:
        records = [c for c in records if c["level"] == level]
    if comp is not None:
        records = [c for c in records if c["compliance_status"] == comp]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/classrooms/<classroom_id>/staff-assignments", methods=["GET"])
def list_classroom_staff(classroom_id):
    _, role = get_auth()
    require_role(role, {"Registrar", "ComplianceOfficer"})
    if classroom_id not in db.classrooms:
        raise errors.not_found("Classroom not found.")
    limit, offset = parse_pagination()
    status = optional_enum(str_arg("status"), STAFF_STATUSES, "status")

    records = [s for s in db.staff_assignments.values() if s["classroom_id"] == classroom_id]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/classrooms/<classroom_id>/promote-waitlist", methods=["POST"])
def promote_waitlist(classroom_id):
    _, role = get_auth()
    require_role(role, {"Registrar"})
    classroom = db.classrooms.get(classroom_id)
    if classroom is None:
        raise errors.not_found("Classroom not found.")

    # Business gates (PRD §3.4): room compliant, room has a free seat.
    # Ordering per §2.10: classroom-not-compliant before classroom-full.
    if classroom["compliance_status"] != "COMPLIANT":
        raise errors.classroom_not_compliant()
    if classroom["placed_count"] >= classroom["capacity"]:
        raise errors.classroom_full()

    app = compliance.select_top_waitlisted(classroom_id)
    if app is None:
        # Empty candidate set: no promotion occurs; not an error.
        # Return the classroom-level result as an empty object body.
        return object_response({}, 200)

    app["status"] = "OFFERED"
    touch(app)
    return object_response(serialize(app), 200)
