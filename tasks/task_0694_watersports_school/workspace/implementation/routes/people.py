"""Student, swim-test, Waiver, Membership routes."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
)
from middleware import get_identity, require_role
from response import success, success_list
from services import derive
from util import (
    parse_date, parse_dt, require_str, require_enum, optional_bool,
    parse_pagination, paginate, touch,
)

bp = Blueprint("people", __name__)
READ_ROLES = {"SchoolAdmin", "Instructor", "Student"}


def _body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object")
    return data


def _check_student_owner(role, user_id, student_id):
    """Student role may only act on their own student record (PRD §2.1)."""
    if role == "Student" and user_id != student_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "not the owning student")


# ------------------------------ Student ---------------------------
@bp.route("/students", methods=["POST"])
def create_student():
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    body = _body()
    school_id = require_str(body, "school_id")
    full_name = require_str(body, "full_name")
    if "birthdate" not in body or body["birthdate"] is None:
        raise err(ERR_VALIDATION, "missing required field: birthdate")
    parse_date(body["birthdate"], "birthdate")  # validate format
    with db.lock():
        if school_id not in db.schools:
            raise err(ERR_NOT_FOUND, "school not found")
        now = db.now_iso()
        sid = db.new_id()
        rec = {
            "id": sid, "school_id": school_id, "full_name": full_name,
            "birthdate": body["birthdate"], "swim_test_status": "UNTESTED",
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.students[sid] = rec
        return success(derive.serialize_student(rec), 201)


@bp.route("/students", methods=["GET"])
def list_students():
    _, role = get_identity()
    require_role(role, {"SchoolAdmin", "Instructor"})
    limit, offset = parse_pagination(request.args)
    school_id = request.args.get("school_id")
    rows = [s for s in db.students.values() if school_id is None or s["school_id"] == school_id]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_student(r) for r in page], limit, offset, total)


@bp.route("/students/<sid>", methods=["GET"])
def get_student(sid):
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.students.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "student not found")
    _check_student_owner(role, user_id, sid)
    return success(derive.serialize_student(rec), 200)


@bp.route("/students/<sid>/swim-test", methods=["POST"])
def swim_test(sid):
    _, role = get_identity()
    require_role(role, {"SchoolAdmin"})
    with db.lock():
        rec = db.students.get(sid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "student not found")
        body = _body()
        result = require_enum(body, "result", {"PASSED", "FAILED"})
        rec["swim_test_status"] = result
        touch(rec)
        return success(derive.serialize_student(rec), 200)


# ------------------------------ Waiver ----------------------------
@bp.route("/waivers", methods=["POST"])
def create_waiver():
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    body = _body()
    student_id = require_str(body, "student_id")
    signed_by = require_str(body, "signed_by")
    is_guardian = optional_bool(body, "is_guardian", False)
    if "expires_at" not in body or body["expires_at"] is None:
        raise err(ERR_VALIDATION, "missing required field: expires_at")
    parse_dt(body["expires_at"], "expires_at")
    with db.lock():
        student = db.students.get(student_id)
        if student is None:
            raise err(ERR_NOT_FOUND, "student not found")
        _check_student_owner(role, user_id, student_id)
        now = db.now_iso()
        wid = db.new_id()
        rec = {
            "id": wid, "student_id": student_id, "signed_by": signed_by,
            "is_guardian": is_guardian, "expires_at": body["expires_at"],
            "status": "SIGNED",
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.waivers[wid] = rec
        # Student.waiver_status is derived; touch student so updated_at/version advance.
        touch(student)
        return success(derive.serialize_waiver(rec), 201)


@bp.route("/waivers", methods=["GET"])
def list_waivers():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    student_id = request.args.get("student_id")
    rows = [w for w in db.waivers.values() if student_id is None or w["student_id"] == student_id]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_waiver(r) for r in page], limit, offset, total)


@bp.route("/waivers/<wid>", methods=["GET"])
def get_waiver(wid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.waivers.get(wid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "waiver not found")
    return success(derive.serialize_waiver(rec), 200)


@bp.route("/waivers/<wid>/revoke", methods=["POST"])
def revoke_waiver(wid):
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    with db.lock():
        rec = db.waivers.get(wid)
        if rec is None:
            raise err(ERR_NOT_FOUND, "waiver not found")
        _check_student_owner(role, user_id, rec["student_id"])
        # Revoke permitted only while status is SIGNED (PRD §3.3).
        if rec["status"] != "SIGNED":
            raise err(ERR_INVALID_STATE, "waiver is not SIGNED")
        rec["status"] = "REVOKED"
        touch(rec)
        student = db.students.get(rec["student_id"])
        if student is not None:
            touch(student)  # waiver_status recomputed (derived); advance student
        return success(derive.serialize_waiver(rec), 200)


# ---------------------------- Membership --------------------------
@bp.route("/memberships", methods=["POST"])
def create_membership():
    user_id, role = get_identity()
    require_role(role, {"SchoolAdmin", "Student"})
    body = _body()
    student_id = require_str(body, "student_id")
    tier = require_enum(body, "tier", {"BASIC", "PREMIUM"})
    with db.lock():
        student = db.students.get(student_id)
        if student is None:
            raise err(ERR_NOT_FOUND, "student not found")
        _check_student_owner(role, user_id, student_id)
        now = db.now_iso()
        mid = db.new_id()
        rec = {
            "id": mid, "student_id": student_id, "tier": tier, "status": "ACTIVE",
            "makeup_credit_balance": 0,
            "created_at": now, "updated_at": now, "version": 1,
            "_seq": db.next_seq(),
        }
        db.memberships[mid] = rec
        return success(derive.serialize_membership(rec), 201)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    student_id = request.args.get("student_id")
    rows = [m for m in db.memberships.values() if student_id is None or m["student_id"] == student_id]
    page, total = paginate(rows, limit, offset)
    return success_list([derive.serialize_membership(r) for r in page], limit, offset, total)


@bp.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = db.memberships.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "membership not found")
    return success(derive.serialize_membership(rec), 200)
