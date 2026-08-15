"""Family, Student, and StudentTeacherLink endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("families", __name__)

FAMILY_READERS = {"SchoolAdmin", "FrontOfficeStaff", "FamilyGuardian"}


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

@bp.route("/conf/families", methods=["POST"])
def create_family():
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin", "FrontOfficeStaff"})
    body = util.get_body()
    util.require_fields(body, ["primary_guardian_name", "email"])
    name = util.require_string(body, "primary_guardian_name")
    email = util.require_string(body, "email")
    phone = util.optional_string(body, "phone", default=None)
    lang = util.optional_string(body, "preferred_language", default="en")

    now = util.now_iso()
    family = {
        "id": util.new_id(),
        "primary_guardian_name": name,
        "email": email,
        "phone": phone,
        "preferred_language": lang,
        "status": "ACTIVE",
        "strikes_cleared_total": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.families[family["id"]] = family
    return response.success_object(serializers.family_view(family), status=201)


@bp.route("/conf/families/<fid>", methods=["GET"])
def get_family(fid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, FAMILY_READERS)
    family = core.get_family_or_404(fid)
    middleware.check_family_owns(role, uid, family["id"])
    return response.success_object(serializers.family_view(family))


@bp.route("/conf/families/<fid>", methods=["PATCH"])
def update_family(fid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, FAMILY_READERS)
    body = util.get_body()
    family = core.get_family_or_404(fid)
    middleware.check_family_owns(role, uid, family["id"])

    for f in ("primary_guardian_name", "email", "preferred_language"):
        if f in body and body[f] is not None:
            if not isinstance(body[f], str) or body[f] == "":
                raise errors.validation(f"{f} must be a non-empty string")
    if "phone" in body and body["phone"] is not None:
        if not isinstance(body["phone"], str):
            raise errors.validation("phone must be a string")

    for f in ("primary_guardian_name", "email", "preferred_language"):
        if f in body and body[f] is not None:
            family[f] = body[f]
    if "phone" in body:
        family["phone"] = body["phone"]

    family["version"] += 1
    family["updated_at"] = util.now_iso()
    return response.success_object(serializers.family_view(family))


@bp.route("/conf/families/<fid>/clear-strikes", methods=["POST"])
def clear_strikes(fid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin", "FrontOfficeStaff"})
    util.get_body()
    family = core.get_family_or_404(fid)
    current = core.family_strike_count(fid)
    family["strikes_cleared_total"] += current
    family["status"] = "ACTIVE"
    family["version"] += 1
    family["updated_at"] = util.now_iso()
    return response.success_object(serializers.family_view(family))


@bp.route("/conf/families/<fid>/students", methods=["GET"])
def list_family_students(fid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, FAMILY_READERS)
    family = core.get_family_or_404(fid)
    middleware.check_family_owns(role, uid, family["id"])
    limit, offset = util.parse_pagination(request.args)
    items = [s for s in db.students.values() if s["family_id"] == fid]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.student_view(s) for s in page],
                                 total, limit, offset)


@bp.route("/conf/families/<fid>/students", methods=["POST"])
def create_student(fid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, FAMILY_READERS)
    body = util.get_body()
    family = core.get_family_or_404(fid)
    middleware.check_family_owns(role, uid, family["id"])
    util.require_fields(body, ["full_name", "grade_level"])
    full_name = util.require_string(body, "full_name")
    grade_level = util.require_int(body, "grade_level", min_value=0, max_value=12)

    now = util.now_iso()
    student = {
        "id": util.new_id(),
        "family_id": fid,
        "full_name": full_name,
        "grade_level": grade_level,
        "enrollment_status": "ENROLLED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.students[student["id"]] = student
    return response.success_object(serializers.student_view(student), status=201)


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

@bp.route("/conf/students/<sid>", methods=["GET"])
def get_student(sid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, FAMILY_READERS)
    student = core.get_student_or_404(sid)
    middleware.check_family_owns(role, uid, student["family_id"])
    return response.success_object(serializers.student_view(student))


@bp.route("/conf/students/<sid>/withdraw", methods=["POST"])
def withdraw_student(sid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin", "FrontOfficeStaff"})
    util.get_body()
    student = core.get_student_or_404(sid)
    if student["enrollment_status"] != "ENROLLED":
        raise errors.invalid_state("student is already WITHDRAWN")
    core.student_withdrawal_cascade(student)
    return response.success_object(serializers.student_view(student))


@bp.route("/conf/students/<sid>/teacher-links", methods=["GET"])
def list_student_links(sid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, FAMILY_READERS)
    student = core.get_student_or_404(sid)
    middleware.check_family_owns(role, uid, student["family_id"])
    limit, offset = util.parse_pagination(request.args)
    items = [l for l in db.links.values() if l["student_id"] == sid]
    items.sort(key=lambda l: l["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.link_view(l) for l in page],
                                 total, limit, offset)


@bp.route("/conf/students/<sid>/teacher-links", methods=["POST"])
def create_link(sid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin", "FrontOfficeStaff"})
    body = util.get_body()
    student = core.get_student_or_404(sid)
    util.require_fields(body, ["teacher_id"])
    teacher_id = body["teacher_id"]
    if not isinstance(teacher_id, str):
        raise errors.validation("teacher_id must be a string")
    # is_homeroom is nullable in storage: omitted -> None (no explicit
    # non-homeroom marking); only an explicit false blocks ELEMENTARY booking.
    if "is_homeroom" not in body or body["is_homeroom"] is None:
        is_homeroom = None
    else:
        is_homeroom = util.optional_bool(body, "is_homeroom")
    required_conference = util.optional_bool(body, "required_conference", default=False)
    core.get_teacher_or_404(teacher_id)
    if core.find_link(sid, teacher_id) is not None:
        raise errors.duplicate_teacher_link()

    link = {
        "id": util.new_id(),
        "student_id": sid,
        "teacher_id": teacher_id,
        "is_homeroom": is_homeroom,
        "required_conference": required_conference,
        "created_at": util.now_iso(),
    }
    db.links[link["id"]] = link
    return response.success_object(serializers.link_view(link), status=201)


@bp.route("/conf/teacher-links/<lid>", methods=["DELETE"])
def delete_link(lid):
    role, _uid = middleware.get_auth()
    middleware.require_roles(role, {"SchoolAdmin", "FrontOfficeStaff"})
    link = core.get_link_or_404(lid)
    del db.links[lid]
    return "", 204
