from datetime import timedelta
from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, get_or_404, make_entity, touch,
    parse_pagination, paginate,
)
from clock import parse_datetime, now
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_ED_CONFLICT, ERR_SCHOOL_NOT_SELECTED, ERR_OPEN_TASKS_REMAIN,
    ERR_DEADLINE_PASSED, ERR_NOT_SUBMITTED, ERR_DEFER_NOT_ALLOWED,
    ERR_APPEAL_WINDOW_CLOSED,
)
from services.applications import recompute_open_task_count

bp = Blueprint("applications", __name__)

APPEAL_WINDOW_DAYS = 30


def serialize(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "school_list_item_id": a["school_list_item_id"],
        "round": a["round"],
        "deadline_utc": a["deadline_utc"],
        "prep_status": a["prep_status"],
        "decision_status": a["decision_status"],
        "open_task_count": a["open_task_count"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/applications", methods=["POST"])
def create_application():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    school_list_item_id = require_string(body, "school_list_item_id")
    rnd = require_enum(body, "round", {"ED", "EA", "RD"})
    deadline_raw = require_string(body, "deadline_utc")
    deadline = parse_datetime(deadline_raw)

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        item = store.school_list_items.get(school_list_item_id)
        if item is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "school_list_item_id does not reference an existing item")
        # cross-student reference rejected
        if item.get("student_id") != student_id:
            raise err(ERR_REFERENCE_NOT_FOUND, "school_list_item_id belongs to a different student")
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")

        # single binding ED rule
        if rnd == "ED":
            for other in store.applications.values():
                if other.get("student_id") != student_id:
                    continue
                if other.get("round") == "ED" and other.get("prep_status") in (
                        "NOT_STARTED", "IN_PROGRESS", "READY", "SUBMITTED"):
                    raise err(ERR_ED_CONFLICT, "Student already has a binding ED application")

        a = make_entity()
        a.update({
            "student_id": student_id,
            "school_list_item_id": school_list_item_id,
            "round": rnd,
            "deadline_utc": deadline_raw,
            "prep_status": "NOT_STARTED",
            "decision_status": "PENDING",
            "open_task_count": 0,
        })
        store.applications[a["id"]] = a
        return success(serialize(a), 201)


@bp.route("/applications/<application_id>", methods=["GET"])
def get_application(application_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        a = get_or_404(store.applications, application_id)
        _assert_access(caller, a)
        return success(serialize(a))


@bp.route("/applications", methods=["GET"])
def list_applications():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_item = request.args.get("school_list_item_id")
    filt_round = request.args.get("round")
    with store.lock:
        rows = [r for r in store.applications.values() if _visible(caller, r)]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_item is not None:
            rows = [r for r in rows if r.get("school_list_item_id") == filt_item]
        if filt_round is not None:
            rows = [r for r in rows if r.get("round") == filt_round]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/applications/<application_id>/start-prep", methods=["POST"])
def start_prep(application_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        a = _owned(caller, application_id)
        if a["prep_status"] != "NOT_STARTED":
            raise err(ERR_INVALID_STATE, "prep_status is not NOT_STARTED")
        item = store.school_list_items.get(a["school_list_item_id"])
        if item is None or item.get("status") != "SELECTED":
            raise err(ERR_SCHOOL_NOT_SELECTED, "Referenced school is not SELECTED")
        a["prep_status"] = "IN_PROGRESS"
        recompute_open_task_count(a)
        touch(a)
        return success(serialize(a))


@bp.route("/applications/<application_id>/mark-ready", methods=["POST"])
def mark_ready(application_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        a = _owned(caller, application_id)
        if a["prep_status"] != "IN_PROGRESS":
            raise err(ERR_INVALID_STATE, "prep_status is not IN_PROGRESS")
        recompute_open_task_count(a)
        if a["open_task_count"] != 0:
            raise err(ERR_OPEN_TASKS_REMAIN, "Open tasks remain")
        a["prep_status"] = "READY"
        recompute_open_task_count(a)
        touch(a)
        return success(serialize(a))


@bp.route("/applications/<application_id>/submit", methods=["POST"])
def submit(application_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        a = _owned(caller, application_id)
        if a["prep_status"] != "READY":
            raise err(ERR_INVALID_STATE, "prep_status is not READY")
        # deadline check
        if not (now() < parse_datetime(a["deadline_utc"])):
            raise err(ERR_DEADLINE_PASSED, "Deadline has passed")
        recompute_open_task_count(a)
        if a["open_task_count"] != 0:
            raise err(ERR_OPEN_TASKS_REMAIN, "Open tasks remain")
        a["prep_status"] = "SUBMITTED"
        touch(a)
        return success(serialize(a))


@bp.route("/applications/<application_id>/record-decision", methods=["POST"])
def record_decision(application_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    decision = require_enum(body, "decision", {"ADMITTED", "DENIED", "WAITLISTED", "DEFERRED"})
    with store.lock:
        a = _owned(caller, application_id)
        cur = a["decision_status"]
        if cur == "PENDING":
            # requires prep_status == SUBMITTED
            valid_targets = {"ADMITTED", "DENIED", "WAITLISTED", "DEFERRED"}
            if decision not in valid_targets:
                raise err(ERR_INVALID_STATE, "Invalid decision from PENDING")
            if a["prep_status"] != "SUBMITTED":
                raise err(ERR_NOT_SUBMITTED, "Application is not SUBMITTED")
            if decision == "DEFERRED" and a["round"] not in ("ED", "EA"):
                raise err(ERR_DEFER_NOT_ALLOWED, "RD rounds cannot defer")
            a["decision_status"] = decision
            touch(a)
        elif cur == "APPEALING":
            if decision not in ("ADMITTED", "DENIED"):
                raise err(ERR_INVALID_STATE, "Appeal outcome must be ADMITTED or DENIED")
            a["decision_status"] = decision
            touch(a)
        else:
            raise err(ERR_INVALID_STATE, "Cannot record decision from %s" % cur)
        return success(serialize(a))


@bp.route("/applications/<application_id>/appeal", methods=["POST"])
def appeal(application_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        a = _owned(caller, application_id)
        if a["decision_status"] != "DENIED":
            raise err(ERR_INVALID_STATE, "decision_status is not DENIED")
        deadline = parse_datetime(a["deadline_utc"])
        window_close = deadline + timedelta(days=APPEAL_WINDOW_DAYS)
        if not (now() < window_close):
            raise err(ERR_APPEAL_WINDOW_CLOSED, "Appeal window has closed")
        a["decision_status"] = "APPEALING"
        # append system appeal-letter task
        from services.applications import append_appeal_task
        append_appeal_task(a)
        recompute_open_task_count(a)
        touch(a)
        return success(serialize(a))


def _owned(caller, application_id):
    a = get_or_404(store.applications, application_id)
    student = store.students.get(a["student_id"])
    if student is None or student.get("counselor_id") != caller.user_id:
        raise err(ERR_FORBIDDEN, "Counselor does not own this application")
    return a


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
        raise err(ERR_FORBIDDEN, "Not permitted on this application")
