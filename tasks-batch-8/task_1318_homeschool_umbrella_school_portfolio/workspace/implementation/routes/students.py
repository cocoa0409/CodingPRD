"""Student endpoints, transcript, and graduation application creation."""
from flask import Blueprint, request

import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object, success_list
from serializers import ser_student, ser_enrollment, ser_graduation_application
from services import core
from services import credits as credits_svc
from validation import get_body, req_string

bp = Blueprint("students", __name__)


@bp.route("/students/<student_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("student", "student_id"),
       parent_chain=(("student", "student_id", db.students),))
def get_student(student_id):
    return success_object(ser_student(db.students[student_id]))


@bp.route("/students/<student_id>/enrollments", methods=["GET"])
@route(ALL_ROLES, ownership=("student", "student_id"),
       parent_chain=(("student", "student_id", db.students),))
def list_student_enrollments(student_id):
    recs = [e for e in db.enrollments.values() if e["student_id"] == student_id]
    year_id = request.args.get("academic_year_id")
    if year_id:
        recs = [e for e in recs if e["academic_year_id"] == year_id]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_enrollment(e) for e in page], limit, offset, total)


@bp.route("/students/<student_id>/transcript", methods=["GET"])
@route(ALL_ROLES, ownership=("student", "student_id"),
       parent_chain=(("student", "student_id", db.students),))
def get_student_transcript(student_id):
    student = db.students[student_id]
    return success_object(credits_svc.transcript_view(student))


@bp.route("/students/<student_id>/graduation-applications", methods=["GET"])
@route(["Parent", "Registrar", "AcademicDirector", "StateAuditor"],
       ownership=("student", "student_id"),
       parent_chain=(("student", "student_id", db.students),))
def list_student_grad_apps(student_id):
    recs = [g for g in db.graduation_applications.values() if g["student_id"] == student_id]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_graduation_application(g) for g in page], limit, offset, total)


@bp.route("/students/<student_id>/enrollments", methods=["POST"])
@route(["Parent"], ownership=("student", "student_id"),
       parent_chain=(("student", "student_id", db.students),))
def create_enrollment(student_id):
    body = get_body()
    academic_year_id = req_string(body, "academic_year_id")
    from validation import req_int
    grade_level = req_int(body, "grade_level", lo=0, hi=12)
    year = db.academic_years.get(academic_year_id)
    if year is None:
        raise_err("ERR_NOT_FOUND", f"academic_year {academic_year_id} not found")
    rec = core.make_record({
        "student_id": student_id,
        "academic_year_id": academic_year_id,
        "grade_level": grade_level,
        "enrollment_status": "REGISTERED",
        "compliance_standing": "GOOD_STANDING",
        "standing_locked": False,
        "provisional_days_counted": 0,
        "provisional_minutes_credited": 0,
        "certified_days_counted": 0,
        "certified_minutes_credited": 0,
        "testing_required": grade_level in year["testing_grades"],
        "testing_satisfied": False,
        "activated_at": None,
        "withdrawn_at": None,
    })
    db.enrollments[rec["id"]] = rec
    return success_object(ser_enrollment(rec), status=201)


@bp.route("/students/<student_id>/graduation-applications", methods=["POST"])
@route(["Parent"], ownership=("student", "student_id"),
       parent_chain=(("student", "student_id", db.students),))
def create_grad_application(student_id):
    body = get_body()
    academic_year_id = req_string(body, "academic_year_id")
    year = db.academic_years.get(academic_year_id)
    if year is None:
        raise_err("ERR_NOT_FOUND", f"academic_year {academic_year_id} not found")
    for g in db.graduation_applications.values():
        if g["student_id"] == student_id and g["status"] in ("SUBMITTED", "APPROVED"):
            raise_err("ERR_ACTIVE_GRADUATION_APPLICATION_EXISTS",
                      "Student already has an active graduation application")
    rec = core.make_record({
        "student_id": student_id,
        "academic_year_id": academic_year_id,
        "status": "SUBMITTED",
        "evaluated_by": None,
        "decision_notes": None,
        "diploma_issued_at": None,
    })
    db.graduation_applications[rec["id"]] = rec
    return success_object(ser_graduation_application(rec), status=201)
