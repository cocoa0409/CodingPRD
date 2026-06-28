from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, get_or_404, make_entity, touch,
    parse_pagination, paginate,
)
from response import success, success_list
from errors import err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE
from services.applications import recompute_open_task_count

bp = Blueprint("recommendations", __name__)

REC_TRANSITIONS = {
    ("REQUESTED", "ACCEPTED"),
    ("ACCEPTED", "SUBMITTED"),
    ("REQUESTED", "DECLINED"),
    ("ACCEPTED", "DECLINED"),
}
REC_TARGETS = {"ACCEPTED", "SUBMITTED", "DECLINED"}


def serialize(r):
    return {
        "id": r["id"],
        "student_id": r["student_id"],
        "recommender_name": r["recommender_name"],
        "recommender_email": r["recommender_email"],
        "rec_type": r["rec_type"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/recommendations", methods=["POST"])
def create_rec():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    recommender_name = require_string(body, "recommender_name")
    recommender_email = require_string(body, "recommender_email")
    rec_type = require_enum(body, "rec_type", {"TEACHER", "COUNSELOR", "OTHER"})

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        _assert_create_owner(caller, student)
        r = make_entity()
        r.update({
            "student_id": student_id,
            "recommender_name": recommender_name,
            "recommender_email": recommender_email,
            "rec_type": rec_type,
            "status": "REQUESTED",
        })
        store.recommendations[r["id"]] = r
        return success(serialize(r), 201)


@bp.route("/recommendations/<rec_id>", methods=["GET"])
def get_rec(rec_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        r = get_or_404(store.recommendations, rec_id)
        _assert_access(caller, r)
        return success(serialize(r))


@bp.route("/recommendations", methods=["GET"])
def list_recs():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_status = request.args.get("status")
    with store.lock:
        rows = [r for r in store.recommendations.values() if _visible(caller, r)]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_status is not None:
            rows = [r for r in rows if r.get("status") == filt_status]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/recommendations/<rec_id>/transition", methods=["POST"])
def transition_rec(rec_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    to_status = require_enum(body, "to_status", REC_TARGETS)
    with store.lock:
        r = get_or_404(store.recommendations, rec_id)
        student = store.students.get(r["student_id"])
        if student is None or student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this recommendation")
        cur = r["status"]
        if (cur, to_status) not in REC_TRANSITIONS:
            raise err(ERR_INVALID_STATE, "Cannot transition recommendation %s -> %s" % (cur, to_status))
        r["status"] = to_status
        touch(r)
        if to_status == "SUBMITTED":
            _close_rec_tasks(student)
        return success(serialize(r))


def _close_rec_tasks(student):
    """Mark RECOMMENDATION tasks DONE across the student's applications."""
    app_ids = {
        a["id"] for a in store.applications.values()
        if a.get("student_id") == student["id"]
    }
    affected = set()
    for task in store.application_tasks.values():
        if task.get("application_id") not in app_ids:
            continue
        if task.get("task_type") != "RECOMMENDATION":
            continue
        if task.get("status") in ("OPEN", "IN_PROGRESS", "BLOCKED"):
            task["status"] = "DONE"
            touch(task)
            affected.add(task["application_id"])
    for app_id in affected:
        app = store.applications.get(app_id)
        if app is not None:
            recompute_open_task_count(app)
            touch(app)


def _assert_create_owner(caller, student):
    if caller.is_counselor:
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")
    elif caller.is_student:
        if student["id"] != caller.user_id:
            raise err(ERR_FORBIDDEN, "Student does not own this resource")


def _visible(caller, r):
    student = store.students.get(r.get("student_id"))
    if student is None:
        return False
    if caller.is_counselor:
        return student.get("counselor_id") == caller.user_id
    if caller.is_student:
        return student["id"] == caller.user_id
    return False


def _assert_access(caller, r):
    if not _visible(caller, r):
        raise err(ERR_FORBIDDEN, "Not permitted on this recommendation")
