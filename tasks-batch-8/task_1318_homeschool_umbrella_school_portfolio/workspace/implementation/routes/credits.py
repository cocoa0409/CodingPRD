"""Course credit endpoints."""
from flask import Blueprint

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object
from serializers import ser_course_credit
from services import core
from services import credits as credits_svc
from validation import (
    get_body, req_string, req_enum, req_int, opt_bool, opt_string,
    CREDIT_SUBJECTS, LETTER_GRADES, CREDIT_VERIFY_DECISIONS,
)

bp = Blueprint("credits", __name__)

_CHAIN = (("course_credit", "credit_id", db.course_credits),)


@bp.route("/enrollments/<enrollment_id>/course-credits", methods=["POST"])
@route(["Parent"], ownership=("enrollment", "enrollment_id"),
       parent_chain=(("enrollment", "enrollment_id", db.enrollments),))
def create_credit(enrollment_id):
    body = get_body()
    subject = req_enum(body, "subject", CREDIT_SUBJECTS)
    course_title = req_string(body, "course_title")
    planned_hours = req_int(body, "planned_hours", lo=1)
    is_lab = opt_bool(body, "is_lab", default=False)
    rec = core.make_record({
        "enrollment_id": enrollment_id,
        "subject": subject,
        "course_title": course_title,
        "is_lab": is_lab,
        "planned_hours": planned_hours,
        "completed_hours": None,
        "letter_grade": None,
        "credit_value": None,
        "status": "PLANNED",
        "posted_at": None,
        "revoked_reason": None,
    })
    db.course_credits[rec["id"]] = rec
    return success_object(ser_course_credit(rec), status=201)


@bp.route("/course-credits/<credit_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("course_credit", "credit_id"), parent_chain=_CHAIN)
def get_credit(credit_id):
    return success_object(ser_course_credit(db.course_credits[credit_id]))


@bp.route("/course-credits/<credit_id>/complete", methods=["POST"])
@route(["Parent"], ownership=("course_credit", "credit_id"), parent_chain=_CHAIN)
def complete_credit(credit_id):
    cc = db.course_credits[credit_id]
    body = get_body()
    completed_hours = req_int(body, "completed_hours", lo=0)
    letter_grade = req_enum(body, "letter_grade", LETTER_GRADES)
    if cc["status"] != "PLANNED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only PLANNED credits may be completed")
    en = db.enrollments.get(cc["enrollment_id"])
    if en["enrollment_status"] not in ("ACTIVE", "COMPLETED"):
        raise_err("ERR_ENROLLMENT_NOT_ACTIVE",
                  "Credit completion requires an ACTIVE or COMPLETED enrollment")
    if completed_hours < credits_svc.MIN_COMPLETION_HOURS:
        raise_err("ERR_CREDIT_HOURS_INSUFFICIENT",
                  "Completion requires completed_hours >= 60")
    cc["completed_hours"] = completed_hours
    cc["letter_grade"] = letter_grade
    cc["credit_value"] = credits_svc.compute_credit_value(completed_hours)
    cc["status"] = "COMPLETED"
    core.touch(cc)
    return success_object(ser_course_credit(cc))


@bp.route("/course-credits/<credit_id>/verify", methods=["POST"])
@route(["Registrar"], parent_chain=_CHAIN)
def verify_credit(credit_id):
    cc = db.course_credits[credit_id]
    body = get_body()
    decision = req_enum(body, "decision", CREDIT_VERIFY_DECISIONS)
    opt_string(body, "notes")
    if cc["status"] != "COMPLETED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only COMPLETED credits may be verified")
    cc["status"] = "VERIFIED" if decision == "APPROVE" else "REJECTED"
    core.touch(cc)
    return success_object(ser_course_credit(cc))


@bp.route("/course-credits/<credit_id>/post", methods=["POST"])
@route(["Registrar"], parent_chain=_CHAIN)
def post_credit(credit_id):
    cc = db.course_credits[credit_id]
    if cc["status"] != "VERIFIED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only VERIFIED credits may be posted")
    en = db.enrollments.get(cc["enrollment_id"])
    student = core.student_of_enrollment(en)
    if student and student["transcript_sealed"]:
        raise_err("ERR_TRANSCRIPT_SEALED", "Transcript is sealed")
    cc["status"] = "POSTED"
    cc["posted_at"] = clock.now_iso()
    core.touch(cc)
    return success_object(ser_course_credit(cc))


@bp.route("/course-credits/<credit_id>/revoke", methods=["POST"])
@route(["Registrar"], parent_chain=_CHAIN)
def revoke_credit(credit_id):
    cc = db.course_credits[credit_id]
    body = get_body()
    reason = req_string(body, "reason")
    if cc["status"] != "POSTED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only POSTED credits may be revoked")
    en = db.enrollments.get(cc["enrollment_id"])
    student = core.student_of_enrollment(en)
    if student and student["transcript_sealed"]:
        raise_err("ERR_TRANSCRIPT_SEALED", "Transcript is sealed")
    cc["status"] = "REVOKED"
    cc["revoked_reason"] = reason
    core.touch(cc)
    return success_object(ser_course_credit(cc))
