"""Applicants and students routes."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, get_json_body, check_fields
from response import success, success_list
from services import serializers as ser
from services.helpers import (make_record, get_or_404, ref_or_404,
                              parent_scope_check, sort_created)

bp = Blueprint("registry", __name__)

READ_ROLES = ("AdmissionDirector", "AdmissionOfficer", "FinancialAidOfficer", "Parent")


# --- Applicants ------------------------------------------------------------

@bp.post("/admissions/applicants")
@require_roles("Parent", "AdmissionOfficer")
def create_applicant(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "family_id": "string",
        "first_name": "string",
        "last_name": "string",
        "date_of_birth": "date",
    }, {"legacy_parent": "bool"})
    parent_scope_check(_uid, _role, vals["family_id"])
    applicant = make_record(db.applicants, {
        "family_id": vals["family_id"],
        "first_name": vals["first_name"],
        "last_name": vals["last_name"],
        "date_of_birth": vals["date_of_birth"],
        "legacy_parent": vals.get("legacy_parent", False),
    })
    return success(ser.applicant_view(applicant), 201)


@bp.get("/admissions/applicants")
@require_roles(*READ_ROLES)
def list_applicants(_uid, _role):
    family_id = request.args.get("family_id")
    if _role == "Parent":
        family_id = _uid  # auto-scope
    items = [a for a in db.applicants.values()
             if family_id is None or a["family_id"] == family_id]
    return success_list([ser.applicant_view(a) for a in sort_created(items)])


@bp.get("/admissions/applicants/<applicantId>")
@require_roles(*READ_ROLES)
def get_applicant(applicantId, _uid, _role):
    applicant = get_or_404(db.applicants, applicantId, "Applicant")
    parent_scope_check(_uid, _role, applicant["family_id"])
    return success(ser.applicant_view(applicant))


# --- Students ---------------------------------------------------------------

@bp.post("/admissions/students")
@require_roles("AdmissionDirector")
def create_student(_uid, _role):
    body = get_json_body()
    vals = check_fields(body, {
        "family_id": "string",
        "first_name": "string",
        "last_name": "string",
        "current_grade_section_id": "string",
    }, {})
    ref_or_404(db.grade_sections, vals["current_grade_section_id"], "GradeSection")
    student = make_record(db.students, {
        "family_id": vals["family_id"],
        "first_name": vals["first_name"],
        "last_name": vals["last_name"],
        "current_grade_section_id": vals["current_grade_section_id"],
        "status": "ACTIVE",
        "source": "DIRECT",
        "re_enrolled_for_cycle_id": None,
    })
    return success(ser.student_view(student), 201)


@bp.get("/admissions/students")
@require_roles(*READ_ROLES)
def list_students(_uid, _role):
    family_id = request.args.get("family_id")
    section_id = request.args.get("current_grade_section_id")
    status = request.args.get("status")
    reenrolled = request.args.get("re_enrolled_for_cycle_id")
    if _role == "Parent":
        family_id = _uid
    items = [s for s in db.students.values()
             if (family_id is None or s["family_id"] == family_id)
             and (section_id is None or s["current_grade_section_id"] == section_id)
             and (status is None or s["status"] == status)
             and (reenrolled is None or s["re_enrolled_for_cycle_id"] == reenrolled)]
    return success_list([ser.student_view(s) for s in sort_created(items)])


@bp.get("/admissions/students/<studentId>")
@require_roles(*READ_ROLES)
def get_student(studentId, _uid, _role):
    student = get_or_404(db.students, studentId, "Student")
    parent_scope_check(_uid, _role, student["family_id"])
    return success(ser.student_view(student))
