"""Stage check routes: schedule, list, get, begin, pass, fail."""

from flask import Blueprint, request

import errors
from db import db, new_common, public, sorted_by_created, touch
from errors import err
from middleware import (as_int, as_str, get_body, get_user_context,
                        parse_pagination, require_fields, require_role)
from response import list_success, success
from services.common import fk_or_404, find_or_404

bp = Blueprint("stage_checks", __name__)


@bp.post("/flight-school/stage-checks")
def create_stage_check():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Instructor"})
    body = get_body()
    require_fields(body, ["enrollment_id", "examiner_instructor_id", "stage_index"])
    enrollment_id = as_str(body, "enrollment_id")
    examiner_instructor_id = as_str(body, "examiner_instructor_id")
    stage_index = as_int(body, "stage_index")
    if stage_index < 1:
        raise err(errors.ERR_INVALID_REQUEST, "stage_index must be >= 1.")
    retry_of = body.get("retry_of_stage_check_id")

    # Existence (left-to-right): enrollment, examiner, retried stage check.
    fk_or_404(db.enrollments, enrollment_id)
    fk_or_404(db.instructors, examiner_instructor_id)
    if retry_of is not None:
        fk_or_404(db.stage_checks, retry_of)

    record = new_common()
    record.update({
        "enrollment_id": enrollment_id,
        "examiner_instructor_id": examiner_instructor_id,
        "stage_index": stage_index,
        "retry_of_stage_check_id": retry_of,
        "result_note": None,
        "status": "SCHEDULED",
    })
    db.stage_checks[record["id"]] = record
    return success(public(record), status=201)


@bp.get("/flight-school/stage-checks")
def list_stage_checks():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    limit, offset = parse_pagination()
    items = list(db.stage_checks.values())
    for field in ("enrollment_id", "examiner_instructor_id",
                  "retry_of_stage_check_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [s for s in items if s.get(field) == val]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(s) for s in page], limit, offset, total)


@bp.get("/flight-school/stage-checks/<stage_check_id>")
def get_stage_check(stage_check_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor"})
    record = find_or_404(db.stage_checks, stage_check_id)
    return success(public(record))


@bp.post("/flight-school/stage-checks/<stage_check_id>/begin")
def begin_stage_check(stage_check_id):
    _, role = get_user_context()
    require_role(role, {"Instructor"})
    sc = find_or_404(db.stage_checks, stage_check_id)
    if sc["status"] != "SCHEDULED":
        raise err(errors.ERR_STAGE_CHECK_NOT_SCHEDULED, "Stage check is not SCHEDULED.")
    enrollment = db.enrollments[sc["enrollment_id"]]
    if enrollment["status"] != "ACTIVE":
        raise err(errors.ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not ACTIVE.")
    if sc["stage_index"] != enrollment["current_stage_index"]:
        raise err(errors.ERR_STAGE_OUT_OF_ORDER, "Stage out of order.")
    sc["status"] = "IN_PROGRESS"
    touch(sc)
    return success(public(sc))


@bp.post("/flight-school/stage-checks/<stage_check_id>/pass")
def pass_stage_check(stage_check_id):
    _, role = get_user_context()
    require_role(role, {"Instructor"})
    sc = find_or_404(db.stage_checks, stage_check_id)
    if sc["status"] != "IN_PROGRESS":
        raise err(errors.ERR_STAGE_CHECK_NOT_IN_PROGRESS, "Stage check is not IN_PROGRESS.")
    body = get_body()
    if "result_note" in body and body["result_note"] is not None:
        sc["result_note"] = as_str(body, "result_note")
    sc["status"] = "PASSED"
    touch(sc)
    enrollment = db.enrollments[sc["enrollment_id"]]
    enrollment["current_stage_index"] += 1
    touch(enrollment)
    return success(public(sc))


@bp.post("/flight-school/stage-checks/<stage_check_id>/fail")
def fail_stage_check(stage_check_id):
    _, role = get_user_context()
    require_role(role, {"Instructor"})
    sc = find_or_404(db.stage_checks, stage_check_id)
    if sc["status"] != "IN_PROGRESS":
        raise err(errors.ERR_STAGE_CHECK_NOT_IN_PROGRESS, "Stage check is not IN_PROGRESS.")
    body = get_body()
    if "result_note" in body and body["result_note"] is not None:
        sc["result_note"] = as_str(body, "result_note")
    sc["status"] = "FAILED"
    touch(sc)
    return success(public(sc))
