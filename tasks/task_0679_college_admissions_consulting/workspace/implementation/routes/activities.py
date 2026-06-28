from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, require_int, get_or_404,
    make_entity, touch, parse_pagination, paginate,
)
from response import success, success_list
from errors import err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST
from services.calculations import recompute_profile_strength

bp = Blueprint("activities", __name__)

CATEGORIES = {"ACADEMIC", "ATHLETIC", "ARTS", "SERVICE", "WORK", "LEADERSHIP"}


def serialize(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "title": a["title"],
        "category": a["category"],
        "hours_per_week": a["hours_per_week"],
        "weeks_per_year": a["weeks_per_year"],
        "tier": a["tier"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/activities", methods=["POST"])
def create_activity():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    title = require_string(body, "title")
    category = require_enum(body, "category", CATEGORIES)
    hours_per_week = require_int(body, "hours_per_week")
    weeks_per_year = require_int(body, "weeks_per_year")
    tier = require_int(body, "tier")
    if hours_per_week < 0:
        raise err(ERR_INVALID_REQUEST, "hours_per_week must be >= 0")
    if not (0 <= weeks_per_year <= 52):
        raise err(ERR_INVALID_REQUEST, "weeks_per_year must be in [0, 52]")
    if not (1 <= tier <= 4):
        raise err(ERR_INVALID_REQUEST, "tier must be in [1, 4]")

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        _assert_owner(caller, student)
        a = make_entity()
        a.update({
            "student_id": student_id,
            "title": title,
            "category": category,
            "hours_per_week": hours_per_week,
            "weeks_per_year": weeks_per_year,
            "tier": tier,
        })
        store.activities[a["id"]] = a
        # recompute student's profile_strength (and dependent school items)
        recompute_profile_strength(student)
        touch(student)
        return success(serialize(a), 201)


@bp.route("/activities/<activity_id>", methods=["GET"])
def get_activity(activity_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        a = get_or_404(store.activities, activity_id)
        _assert_access(caller, a)
        return success(serialize(a))


@bp.route("/activities", methods=["GET"])
def list_activities():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_category = request.args.get("category")
    with store.lock:
        rows = [r for r in store.activities.values() if _visible(caller, r)]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_category is not None:
            rows = [r for r in rows if r.get("category") == filt_category]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


def _assert_owner(caller, student):
    if caller.is_counselor:
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")
    elif caller.is_student:
        if student["id"] != caller.user_id:
            raise err(ERR_FORBIDDEN, "Student does not own this resource")


def _visible(caller, a):
    student = store.students.get(a.get("student_id"))
    if student is None:
        return False
    if caller.is_counselor:
        return student.get("counselor_id") == caller.user_id
    if caller.is_student:
        return student["id"] == caller.user_id
    return False


def _assert_access(caller, a):
    if not _visible(caller, a):
        raise err(ERR_FORBIDDEN, "Not permitted on this activity")
