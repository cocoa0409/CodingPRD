"""Endorsement routes: issue, list, get, revoke."""

from flask import Blueprint, request

import errors
from db import db, new_common, public, sorted_by_created, touch
from errors import err
from middleware import (as_str, get_body, get_user_context, parse_pagination,
                        require_fields, require_role)
from response import list_success, success
from services.common import fk_or_404, find_or_404

bp = Blueprint("endorsements", __name__)

ENDORSEMENT_CODES = {"SOLO", "XC", "COMPLEX", "TAILWHEEL"}


@bp.post("/flight-school/endorsements")
def issue_endorsement():
    _, role = get_user_context()
    require_role(role, {"Instructor"})
    body = get_body()
    require_fields(body, ["enrollment_id", "instructor_id", "endorsement_code"])
    enrollment_id = as_str(body, "enrollment_id")
    instructor_id = as_str(body, "instructor_id")
    endorsement_code = body["endorsement_code"]
    if endorsement_code not in ENDORSEMENT_CODES:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid endorsement_code.")

    # Existence (left-to-right): enrollment, instructor.
    fk_or_404(db.enrollments, enrollment_id)
    instructor = fk_or_404(db.instructors, instructor_id)

    # Referential: instructor must be authorized for the code.
    if endorsement_code not in instructor.get("authorized_endorsement_codes", []):
        raise err(errors.ERR_ENDORSEMENT_NOT_AUTHORIZED,
                  "Instructor is not authorized for this endorsement code.")

    record = new_common()
    record.update({
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "endorsement_code": endorsement_code,
        "status": "VALID",
    })
    db.endorsements[record["id"]] = record
    return success(public(record), status=201)


@bp.get("/flight-school/endorsements")
def list_endorsements():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    limit, offset = parse_pagination()
    items = list(db.endorsements.values())
    for field in ("enrollment_id", "instructor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [e for e in items if e.get(field) == val]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(e) for e in page], limit, offset, total)


@bp.get("/flight-school/endorsements/<endorsement_id>")
def get_endorsement(endorsement_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    record = find_or_404(db.endorsements, endorsement_id)
    return success(public(record))


@bp.post("/flight-school/endorsements/<endorsement_id>/revoke")
def revoke_endorsement(endorsement_id):
    _, role = get_user_context()
    require_role(role, {"Instructor"})
    endorsement = find_or_404(db.endorsements, endorsement_id)
    if endorsement["status"] != "VALID":
        raise err(errors.ERR_ENDORSEMENT_NOT_VALID, "Endorsement is not VALID.")
    endorsement["status"] = "REVOKED"
    touch(endorsement)
    return success(public(endorsement))
