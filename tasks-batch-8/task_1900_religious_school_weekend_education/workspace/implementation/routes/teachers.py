"""Teacher endpoints."""

from flask import Blueprint

from db import store
from middleware import require_roles
from response import success_object
from errors import (
    ApiError, invalid_request, invalid_state,
    ERR_BACKGROUND_CHECK_REQUIRED,
)
from services.core import (
    base_record, touch, public, get_teacher, reevaluate_milestones_for_section,
)

bp = Blueprint("teachers", __name__)


@bp.route("/school/teachers", methods=["POST"])
def create_teacher():
    require_roles(["SchoolAdmin"])
    from flask import request
    body = request.get_json(silent=True) or {}
    full_name = body.get("full_name")
    email = body.get("email")
    bg = body.get("background_check_cleared", False)
    if not isinstance(full_name, str) or not full_name:
        raise invalid_request("full_name is required")
    if not isinstance(email, str) or not email:
        raise invalid_request("email is required")
    if not isinstance(bg, bool):
        raise invalid_request("background_check_cleared must be boolean")
    rec = base_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "background_check_cleared": bg,
        "status": "APPLIED",
    })
    store.teachers[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/school/teachers/<teacher_id>", methods=["GET"])
def get_teacher_endpoint(teacher_id):
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    rec = get_teacher(teacher_id)
    return success_object(public(rec))


@bp.route("/school/teachers/<teacher_id>/vet", methods=["POST"])
def vet_teacher(teacher_id):
    require_roles(["SchoolAdmin"])
    teacher = get_teacher(teacher_id)
    if teacher["status"] != "APPLIED":
        raise invalid_state("Teacher is not in APPLIED")
    if not teacher.get("background_check_cleared"):
        raise ApiError(ERR_BACKGROUND_CHECK_REQUIRED, 409, "background check not cleared")
    teacher["status"] = "VETTED"
    touch(teacher)
    return success_object(public(teacher))


@bp.route("/school/teachers/<teacher_id>/hire", methods=["POST"])
def hire_teacher(teacher_id):
    require_roles(["SchoolAdmin"])
    teacher = get_teacher(teacher_id)
    if teacher["status"] != "VETTED":
        raise invalid_state("Teacher is not in VETTED")
    teacher["status"] = "HIRED"
    touch(teacher)
    return success_object(public(teacher))


@bp.route("/school/teachers/<teacher_id>/separate", methods=["POST"])
def separate_teacher(teacher_id):
    require_roles(["SchoolAdmin"])
    teacher = get_teacher(teacher_id)
    if teacher["status"] not in ("VETTED", "HIRED"):
        raise invalid_state("Teacher cannot be separated from current state")
    was_hired = teacher["status"] == "HIRED"
    teacher["status"] = "SEPARATED"
    touch(teacher)

    if was_hired:
        # Cascade hop 1: unstaff OPEN/FULL sections assigned to this teacher
        affected_sections = []
        for sec in store.sections.values():
            if sec.get("teacher_id") == teacher_id and sec["status"] in ("OPEN", "FULL"):
                sec["teacher_id"] = None
                touch(sec)
                affected_sections.append(sec)
        # Cascade hop 2: their SCHEDULED sessions -> CANCELLED (TEACHER_SEPARATION)
        for sec in affected_sections:
            for s in store.sessions.values():
                if s["section_id"] == sec["id"] and s["status"] == "SCHEDULED":
                    s["status"] = "CANCELLED"
                    s["cancel_reason"] = "TEACHER_SEPARATION"
                    touch(s)
        # Cascade hop 3: recompute attendance + re-evaluate milestones
        for sec in affected_sections:
            reevaluate_milestones_for_section(sec["id"])

    return success_object(public(teacher))
