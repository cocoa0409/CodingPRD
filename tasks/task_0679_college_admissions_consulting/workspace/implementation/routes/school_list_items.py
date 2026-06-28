from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_number, require_int, opt_enum,
    require_int as _ri, get_or_404, make_entity, touch, parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_STALE_STUDENT_VERSION, ERR_INVALID_STATE,
)
from services.calculations import recompute_school_item, recompute_list_locked

bp = Blueprint("school_list_items", __name__)


def serialize(it):
    return {
        "id": it["id"],
        "student_id": it["student_id"],
        "school_name": it["school_name"],
        "admit_rate": it["admit_rate"],
        "median_sat": it["median_sat"],
        "round": it["round"],
        "admit_probability": it["admit_probability"],
        "classification": it["classification"],
        "status": it["status"],
        "created_at": it["created_at"],
        "updated_at": it["updated_at"],
        "version": it["version"],
    }


@bp.route("/school-list-items", methods=["POST"])
def create_item():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    school_name = require_string(body, "school_name")
    admit_rate = require_number(body, "admit_rate")
    median_sat = require_int(body, "median_sat")
    rnd = opt_enum(body, "round", {"ED", "EA", "RD", "NONE"}, "NONE")

    if not (admit_rate > 0.0 and admit_rate <= 1.0):
        raise err(ERR_INVALID_REQUEST, "admit_rate must be in (0.0, 1.0]")
    if not (400 <= median_sat <= 1600):
        raise err(ERR_INVALID_REQUEST, "median_sat must be in [400, 1600]")

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")

        it = make_entity()
        it.update({
            "student_id": student_id,
            "school_name": school_name,
            "admit_rate": admit_rate,
            "median_sat": median_sat,
            "round": rnd,
            "admit_probability": 0,
            "classification": "REACH",
            "status": "CANDIDATE",
        })
        recompute_school_item(it, student)
        store.school_list_items[it["id"]] = it
        return success(serialize(it), 201)


@bp.route("/school-list-items/<item_id>", methods=["GET"])
def get_item(item_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        it = get_or_404(store.school_list_items, item_id)
        _assert_access(caller, it)
        return success(serialize(it))


@bp.route("/school-list-items", methods=["GET"])
def list_items():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_status = request.args.get("status")
    with store.lock:
        rows = list(store.school_list_items.values())
        rows = [r for r in rows if _visible(caller, r)]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_status is not None:
            rows = [r for r in rows if r.get("status") == filt_status]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/school-list-items/<item_id>/select", methods=["POST"])
def select_item(item_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    expected_student_version = require_int(body, "expected_student_version")
    with store.lock:
        it = get_or_404(store.school_list_items, item_id)
        student = store.students.get(it["student_id"])
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this item")
        # OCC before state check per PRD §2.10
        if expected_student_version != student.get("version"):
            raise err(ERR_STALE_STUDENT_VERSION, "expected_student_version is stale")
        if it["status"] != "CANDIDATE":
            raise err(ERR_INVALID_STATE, "Item is not CANDIDATE")
        it["status"] = "SELECTED"
        touch(it)
        recompute_list_locked(student)
        touch(student)
        return success(serialize(it))


@bp.route("/school-list-items/<item_id>/drop", methods=["POST"])
def drop_item(item_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        it = get_or_404(store.school_list_items, item_id)
        student = store.students.get(it["student_id"])
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this item")
        if it["status"] not in ("CANDIDATE", "SELECTED"):
            raise err(ERR_INVALID_STATE, "Item cannot be dropped from %s" % it["status"])
        it["status"] = "DROPPED"
        touch(it)
        old_lock = student.get("list_locked")
        recompute_list_locked(student)
        if student.get("list_locked") != old_lock:
            touch(student)
        return success(serialize(it))


def _visible(caller, it):
    student = store.students.get(it.get("student_id"))
    if student is None:
        return False
    if caller.is_counselor:
        return student.get("counselor_id") == caller.user_id
    if caller.is_student:
        return student["id"] == caller.user_id
    return False


def _assert_access(caller, it):
    if not _visible(caller, it):
        raise err(ERR_FORBIDDEN, "Not permitted on this item")
