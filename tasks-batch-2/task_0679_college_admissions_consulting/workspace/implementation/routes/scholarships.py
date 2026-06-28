from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, require_int, get_or_404,
    make_entity, touch, parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_AWARD_NOT_ADMITTED,
)
from services.calculations import recompute_net_aid

bp = Blueprint("scholarships", __name__)

AWARD_TRANSITIONS = {
    ("OFFERED", "ACCEPTED"),
    ("OFFERED", "DECLINED"),
}
AWARD_TARGETS = {"ACCEPTED", "DECLINED"}


def serialize(a):
    return {
        "id": a["id"],
        "student_id": a["student_id"],
        "application_id": a["application_id"],
        "award_name": a["award_name"],
        "award_type": a["award_type"],
        "gross_amount_cents": a["gross_amount_cents"],
        "net_amount_cents": a["net_amount_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/scholarships", methods=["POST"])
def create_award():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    student_id = require_string(body, "student_id")
    award_name = require_string(body, "award_name")
    award_type = require_enum(body, "award_type", {"MERIT", "NEED", "EXTERNAL"})
    gross_amount_cents = require_int(body, "gross_amount_cents")
    if gross_amount_cents <= 0:
        raise err(ERR_INVALID_REQUEST, "gross_amount_cents must be > 0")
    application_id = body.get("application_id", None)
    if application_id is not None and not isinstance(application_id, str):
        raise err(ERR_INVALID_REQUEST, "application_id must be a string or null")

    with store.lock:
        student = store.students.get(student_id)
        if student is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "student_id does not reference an existing student")
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")
        if application_id is not None:
            app = store.applications.get(application_id)
            if app is None:
                raise err(ERR_REFERENCE_NOT_FOUND, "application_id does not reference an existing application")
            if app.get("student_id") != student_id:
                raise err(ERR_REFERENCE_NOT_FOUND, "application_id belongs to a different student")

        a = make_entity()
        a.update({
            "student_id": student_id,
            "application_id": application_id,
            "award_name": award_name,
            "award_type": award_type,
            "gross_amount_cents": gross_amount_cents,
            "net_amount_cents": 0,
            "status": "OFFERED",
        })
        store.scholarships[a["id"]] = a
        # recompute net amounts across the student's awards
        recompute_net_aid(student_id)
        return success(serialize(a), 201)


@bp.route("/scholarships/<award_id>", methods=["GET"])
def get_award(award_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        a = get_or_404(store.scholarships, award_id)
        _assert_access(caller, a)
        return success(serialize(a))


@bp.route("/scholarships", methods=["GET"])
def list_awards():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_student = request.args.get("student_id")
    filt_app = request.args.get("application_id")
    filt_status = request.args.get("status")
    with store.lock:
        rows = [r for r in store.scholarships.values() if _visible(caller, r)]
        if filt_student is not None:
            rows = [r for r in rows if r.get("student_id") == filt_student]
        if filt_app is not None:
            rows = [r for r in rows if r.get("application_id") == filt_app]
        if filt_status is not None:
            rows = [r for r in rows if r.get("status") == filt_status]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/scholarships/<award_id>/transition", methods=["POST"])
def transition_award(award_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    to_status = require_enum(body, "to_status", AWARD_TARGETS)
    with store.lock:
        a = get_or_404(store.scholarships, award_id)
        student = store.students.get(a["student_id"])
        if student is None or student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this award")
        cur = a["status"]
        if (cur, to_status) not in AWARD_TRANSITIONS:
            raise err(ERR_INVALID_STATE, "Cannot transition award %s -> %s" % (cur, to_status))
        if to_status == "ACCEPTED" and a["award_type"] in ("MERIT", "NEED"):
            app = store.applications.get(a.get("application_id")) if a.get("application_id") else None
            if app is None or app.get("decision_status") != "ADMITTED":
                raise err(ERR_AWARD_NOT_ADMITTED, "Tied application must be ADMITTED")
        a["status"] = to_status
        touch(a)
        recompute_net_aid(a["student_id"])
        return success(serialize(a))


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
        raise err(ERR_FORBIDDEN, "Not permitted on this award")
