from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_int, get_or_404, make_entity, touch,
    parse_pagination, paginate,
)
from clock import now
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_WORD_LIMIT_EXCEEDED, ERR_REVIEW_CAPACITY_EXCEEDED,
    ERR_NO_VERSION_TO_REVIEW, ERR_REVISION_REQUIRED,
)
from services.applications import recompute_open_task_count

bp = Blueprint("essays", __name__)


def serialize(e):
    return {
        "id": e["id"],
        "student_id": e["student_id"],
        "application_id": e["application_id"],
        "prompt": e["prompt"],
        "word_limit": e["word_limit"],
        "status": e["status"],
        "revision_round": e["revision_round"],
        "latest_version_no": e["latest_version_no"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_version(v):
    return {
        "id": v["id"],
        "essay_id": v["essay_id"],
        "version_no": v["version_no"],
        "word_count": v["word_count"],
        "body": v["body"],
        "submitted_by_role": v["submitted_by_role"],
        "created_at": v["created_at"],
    }


# --------------------------------------------------------------------------
# Essay CRUD
# --------------------------------------------------------------------------
@bp.route("/essays", methods=["POST"])
def create_essay():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    prompt = require_string(body, "prompt")
    word_limit = require_int(body, "word_limit")
    if word_limit <= 0:
        raise err(ERR_INVALID_REQUEST, "word_limit must be > 0")
    application_id = body.get("application_id", None)
    if application_id is not None and not isinstance(application_id, str):
        raise err(ERR_INVALID_REQUEST, "application_id must be a string or null")

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        if application_id is not None:
            app = store.applications.get(application_id)
            if app is None:
                raise err(ERR_REFERENCE_NOT_FOUND, "application_id does not reference an existing application")
            if app.get("student_id") != student_id:
                raise err(ERR_REFERENCE_NOT_FOUND, "application_id belongs to a different student")
        _assert_create_owner(caller, student)

        e = make_entity()
        e.update({
            "student_id": student_id,
            "application_id": application_id,
            "prompt": prompt,
            "word_limit": word_limit,
            "status": "DRAFTING",
            "revision_round": 0,
            "latest_version_no": 0,
        })
        store.essays[e["id"]] = e
        return success(serialize(e), 201)


@bp.route("/essays/<essay_id>", methods=["GET"])
def get_essay(essay_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        e = get_or_404(store.essays, essay_id)
        _assert_access(caller, e)
        return success(serialize(e))


@bp.route("/essays", methods=["GET"])
def list_essays():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_app = request.args.get("application_id")
    with store.lock:
        rows = [r for r in store.essays.values() if _visible(caller, r)]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_app is not None:
            rows = [r for r in rows if r.get("application_id") == filt_app]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Essay transitions
# --------------------------------------------------------------------------
@bp.route("/essays/<essay_id>/submit-version", methods=["POST"])
def submit_version(essay_id):
    caller = authenticate()
    require_roles(caller, {"Student", "Counselor"})
    body = get_json_body()
    word_count = require_int(body, "word_count")
    if word_count < 0:
        raise err(ERR_INVALID_REQUEST, "word_count must be >= 0")
    submit_body = require_string(body, "body")

    with store.lock:
        e = get_or_404(store.essays, essay_id)
        student = store.students.get(e["student_id"])
        _assert_submit_owner(caller, student)
        if e["status"] != "DRAFTING":
            raise err(ERR_INVALID_STATE, "Essay is not DRAFTING")
        # word limit
        if word_count > e["word_limit"]:
            raise err(ERR_WORD_LIMIT_EXCEEDED, "word_count exceeds word_limit")
        # weekly review capacity for the owning counselor
        counselor_id = student.get("counselor_id")
        counselor = store.counselors.get(counselor_id)
        capacity = counselor.get("weekly_review_capacity", 0) if counselor else 0
        used = _reviews_this_week(counselor_id)
        if used >= capacity:
            raise err(ERR_REVIEW_CAPACITY_EXCEEDED, "Weekly review capacity reached")

        # role label for submitted_by_role
        role_label = "Counselor" if caller.is_counselor else "Student"
        new_no = e["latest_version_no"] + 1
        v = make_entity(has_version=False)
        v.update({
            "essay_id": e["id"],
            "version_no": new_no,
            "word_count": word_count,
            "body": submit_body,
            "submitted_by_role": role_label,
            # logical-clock instant for ISO-week capacity accounting
            "_submitted_clock": now().isoformat(),
        })
        store.essay_versions[v["id"]] = v
        e["latest_version_no"] = new_no
        e["status"] = "IN_REVIEW"
        touch(e)
        return success(serialize(e))


@bp.route("/essays/<essay_id>/request-revision", methods=["POST"])
def request_revision(essay_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        e = get_or_404(store.essays, essay_id)
        _assert_counselor_owner(caller, e)
        if e["status"] != "IN_REVIEW":
            raise err(ERR_INVALID_STATE, "Essay is not IN_REVIEW")
        if e["latest_version_no"] < 1:
            raise err(ERR_NO_VERSION_TO_REVIEW, "Essay has no version to review")
        e["revision_round"] = e["revision_round"] + 1
        e["status"] = "REVISION_REQUESTED"
        # cascade: demote a READY application linked to this essay
        if e.get("application_id"):
            app = store.applications.get(e["application_id"])
            if app is not None and app.get("prep_status") == "READY":
                app["prep_status"] = "IN_PROGRESS"
                recompute_open_task_count(app)
                touch(app)
        touch(e)
        return success(serialize(e))


@bp.route("/essays/<essay_id>/resume-drafting", methods=["POST"])
def resume_drafting(essay_id):
    caller = authenticate()
    require_roles(caller, {"Student", "Counselor"})
    with store.lock:
        e = get_or_404(store.essays, essay_id)
        student = store.students.get(e["student_id"])
        _assert_submit_owner(caller, student)
        if e["status"] != "REVISION_REQUESTED":
            raise err(ERR_INVALID_STATE, "Essay is not REVISION_REQUESTED")
        e["status"] = "DRAFTING"
        touch(e)
        return success(serialize(e))


@bp.route("/essays/<essay_id>/approve", methods=["POST"])
def approve(essay_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        e = get_or_404(store.essays, essay_id)
        _assert_counselor_owner(caller, e)
        if e["status"] not in ("DRAFTING", "IN_REVIEW"):
            raise err(ERR_INVALID_STATE, "Essay cannot be approved from %s" % e["status"])
        if e["latest_version_no"] < 1:
            raise err(ERR_NO_VERSION_TO_REVIEW, "Essay has no version to review")
        if e["revision_round"] < 1:
            raise err(ERR_REVISION_REQUIRED, "At least one review cycle required")
        e["status"] = "APPROVED"
        # cascade: mark linked ESSAY tasks DONE
        if e.get("application_id"):
            app = store.applications.get(e["application_id"])
            if app is not None:
                changed = False
                for task in store.application_tasks.values():
                    if task.get("application_id") != app["id"]:
                        continue
                    if task.get("task_type") != "ESSAY":
                        continue
                    if task.get("status") in ("OPEN", "IN_PROGRESS", "BLOCKED"):
                        task["status"] = "DONE"
                        touch(task)
                        changed = True
                if changed:
                    recompute_open_task_count(app)
                    touch(app)
        touch(e)
        return success(serialize(e))


@bp.route("/essays/<essay_id>/abandon", methods=["POST"])
def abandon(essay_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    with store.lock:
        e = get_or_404(store.essays, essay_id)
        _assert_counselor_owner(caller, e)
        if e["status"] not in ("DRAFTING", "IN_REVIEW", "REVISION_REQUESTED"):
            raise err(ERR_INVALID_STATE, "Essay cannot be abandoned from %s" % e["status"])
        e["status"] = "ABANDONED"
        touch(e)
        return success(serialize(e))


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _reviews_this_week(counselor_id):
    """Count EssayVersions submitted in the current ISO week (logical clock)
    for essays whose owning student is assigned to this counselor."""
    cur_year, cur_week, _ = now().isocalendar()
    from clock import parse_datetime
    count = 0
    for v in store.essay_versions.values():
        essay = store.essays.get(v.get("essay_id"))
        if essay is None:
            continue
        student = store.students.get(essay.get("student_id"))
        if student is None or student.get("counselor_id") != counselor_id:
            continue
        stamp = v.get("_submitted_clock")
        if not stamp:
            continue
        dt = parse_datetime(stamp)
        y, w, _ = dt.isocalendar()
        if y == cur_year and w == cur_week:
            count += 1
    return count


def _assert_create_owner(caller, student):
    if caller.is_counselor:
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")
    elif caller.is_student:
        if student["id"] != caller.user_id:
            raise err(ERR_FORBIDDEN, "Student does not own this resource")


def _assert_submit_owner(caller, student):
    _assert_create_owner(caller, student)


def _assert_counselor_owner(caller, essay):
    student = store.students.get(essay.get("student_id"))
    if student is None or student.get("counselor_id") != caller.user_id:
        raise err(ERR_FORBIDDEN, "Counselor does not own this essay")


def _visible(caller, e):
    student = store.students.get(e.get("student_id"))
    if student is None:
        return False
    if caller.is_counselor:
        return student.get("counselor_id") == caller.user_id
    if caller.is_student:
        return student["id"] == caller.user_id
    return False


def _assert_access(caller, e):
    if not _visible(caller, e):
        raise err(ERR_FORBIDDEN, "Not permitted on this essay")
