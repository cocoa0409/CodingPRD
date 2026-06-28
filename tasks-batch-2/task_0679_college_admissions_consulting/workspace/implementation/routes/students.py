from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_int, require_number, opt_int,
    require_enum, check_range, get_or_404, make_entity, touch,
    parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INTAKE_INCOMPLETE, ERR_APPLICATIONS_IN_FLIGHT, ERR_CONTRACT_ALREADY_ACTIVE,
)
from services.calculations import recompute_profile_strength

bp = Blueprint("students", __name__)

VALID_TRANSITIONS = {
    ("PROSPECT", "ONBOARDED"),
    ("ACTIVE", "GRADUATED"),
    ("PROSPECT", "WITHDRAWN"),
    ("ONBOARDED", "WITHDRAWN"),
    ("ACTIVE", "WITHDRAWN"),
}
# to_status values the counselor may request directly
DIRECT_TARGETS = {"ONBOARDED", "GRADUATED", "WITHDRAWN"}


def serialize(s):
    return {
        "id": s["id"],
        "counselor_id": s["counselor_id"],
        "full_name": s["full_name"],
        "email": s["email"],
        "grad_year": s["grad_year"],
        "gpa": s["gpa"],
        "sat_total": s["sat_total"],
        "intake_status": s["intake_status"],
        "profile_strength": s["profile_strength"],
        "list_locked": s["list_locked"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/students", methods=["POST"])
def create_student():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    counselor_id = require_string(body, "counselor_id")
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    grad_year = require_int(body, "grad_year")
    gpa = require_number(body, "gpa")
    sat_total = opt_int(body, "sat_total", 0)

    # body well-formedness ranges
    check_range(grad_year, "grad_year", lo=2026)
    check_range(gpa, "gpa", lo=0.0, hi=4.0)
    if sat_total != 0:
        check_range(sat_total, "sat_total", lo=400, hi=1600)

    with store.lock:
        # ownership: counselor can only create students assigned to themselves
        if counselor_id != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor may only create students assigned to themselves")
        # FK existence
        if counselor_id not in store.counselors:
            raise err(ERR_REFERENCE_NOT_FOUND, "counselor_id does not reference an existing counselor")

        s = make_entity()
        s.update({
            "counselor_id": counselor_id,
            "full_name": full_name,
            "email": email,
            "grad_year": grad_year,
            "gpa": gpa,
            "sat_total": sat_total,
            "intake_status": "PROSPECT",
            "profile_strength": 0,
            "list_locked": False,
        })
        store.students[s["id"]] = s
        return success(serialize(s), 201)


@bp.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        s = get_or_404(store.students, student_id)
        _assert_student_access(caller, s)
        return success(serialize(s))


@bp.route("/students", methods=["GET"])
def list_students():
    caller = authenticate()
    require_roles(caller, {"Counselor", "PlatformAdmin"})
    limit, offset = parse_pagination()
    filt_counselor = request.args.get("counselor_id")
    with store.lock:
        rows = list(store.students.values())
        if caller.is_counselor:
            rows = [r for r in rows if r.get("counselor_id") == caller.user_id]
        if filt_counselor is not None:
            rows = [r for r in rows if r.get("counselor_id") == filt_counselor]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize(r) for r in page], limit, offset, total)


@bp.route("/students/<student_id>/transition", methods=["POST"])
def transition_student(student_id):
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    to_status = require_enum(body, "to_status", DIRECT_TARGETS)

    with store.lock:
        s = get_or_404(store.students, student_id)
        if s.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")

        cur = s["intake_status"]
        if (cur, to_status) not in VALID_TRANSITIONS:
            raise err(ERR_INVALID_STATE, "Cannot transition student %s -> %s" % (cur, to_status))

        if to_status == "ONBOARDED":
            _check_intake_complete(s)
            s["intake_status"] = "ONBOARDED"
            recompute_profile_strength(s)
            touch(s)
        elif to_status == "GRADUATED":
            _check_can_graduate(s)
            s["intake_status"] = "GRADUATED"
            touch(s)
        elif to_status == "WITHDRAWN":
            if cur == "ACTIVE":
                _check_no_active_contract(s)
            s["intake_status"] = "WITHDRAWN"
            touch(s)

        return success(serialize(s))


def _check_intake_complete(student):
    has_activity = any(
        a.get("student_id") == student["id"] for a in store.activities.values()
    )
    if not has_activity or student.get("sat_total", 0) == 0:
        raise err(ERR_INTAKE_INCOMPLETE, "Onboard requires >=1 activity and sat_total != 0")


def _check_can_graduate(student):
    for app in store.applications.values():
        if app.get("student_id") != student["id"]:
            continue
        if app.get("decision_status") != "PENDING" or app.get("prep_status") == "SUBMITTED":
            continue
        raise err(ERR_APPLICATIONS_IN_FLIGHT, "Application still in flight")
    _check_no_active_contract(student)


def _check_no_active_contract(student):
    for c in store.contracts.values():
        if c.get("student_id") == student["id"] and c.get("status") == "ACTIVE":
            raise err(ERR_CONTRACT_ALREADY_ACTIVE, "Student has an ACTIVE contract")


def _assert_student_access(caller, student):
    if caller.is_counselor:
        if student.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this student")
    elif caller.is_student:
        if student["id"] != caller.user_id:
            raise err(ERR_FORBIDDEN, "Student does not own this resource")
