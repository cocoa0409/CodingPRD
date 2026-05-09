"""Enrollment endpoints."""
import datetime

from flask import Blueprint, request

from db import bump, iso_now_ms, make_common_fields, store
from errors import raise_api
from middleware import require_roles
from response import success
from services import audit
from services.lookup import get_course, get_enrollment, get_student
from services.progress import recompute_progress
from services.rounding import round_half_up_int

enrollments_bp = Blueprint("enrollments", __name__)


def _compute_paid_amount(course):
    list_price = int(course["list_price_cents"])
    disc = int(course.get("discount_percent", 0))
    eff = max(0, min(80, disc))
    raw = list_price * (100 - eff) / 100
    return round_half_up_int(raw)


def _enrollment_view(enr):
    """Refresh derived fields and return a copy."""
    recompute_progress(enr, run_at_risk=False)
    return dict(enr)


@enrollments_bp.route("/courses/<course_id>/enrollments", methods=["POST"])
def create_enrollment(course_id):
    user_id, _ = require_roles("Student")
    course = get_course(course_id)
    body = request.get_json(silent=True) or {}
    student_id = body.get("student_id")
    if not student_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "student_id required")
    if student_id != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Caller is not the student")
    student = get_student(student_id)

    # PRD §3.1: "While the course is FROZEN, ... creating a new enrollment" is blocked
    # with ERR_COURSE_FROZEN. This frozen-check fires before the generic
    # ERR_COURSE_NOT_PUBLISHED state-check for enrollment specifically.
    if course.get("posture") == "FROZEN":
        raise_api("ERR_COURSE_FROZEN", "Course is frozen")
    if course["status"] != "PUBLISHED":
        raise_api("ERR_COURSE_NOT_PUBLISHED", "Course must be PUBLISHED to enroll")

    paid = _compute_paid_amount(course)
    enrolled_at = iso_now_ms()
    enr = {
        **make_common_fields(),
        "course_id": course_id,
        "student_id": student_id,
        "class_group_id": None,
        "payment_status": "PAID",
        "learning_status": "ACTIVE",
        "paid_amount_cents": paid,
        "enrolled_at": enrolled_at,
        "chapter_completion_percent": 0.0,
        "watch_duration_percent": 0.0,
        "progress_percent": 0.0,
        "attendance_count": 0,
        "refund_amount_cents": None,
    }
    store.enrollments[enr["id"]] = enr

    audit.append(
        actor_role="Student",
        actor_id=user_id,
        action="ENROLLMENT_CREATED",
        subject_type="ENROLLMENT",
        subject_id=enr["id"],
        detail={
            "course_id": course_id,
            "student_id": student_id,
            "paid_amount_cents": paid,
        },
    )
    return success(_enrollment_view(enr), http_status=201)


@enrollments_bp.route("/enrollments/<enrollment_id>", methods=["GET"])
def get_one_enrollment(enrollment_id):
    user_id, role = require_roles("Student", "Instructor", "TeachingAssistant", "AcademicAdmin")
    enr = get_enrollment(enrollment_id)
    if role == "Student":
        if enr["student_id"] != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the enrolled student")
    elif role == "Instructor":
        course = store.courses.get(enr["course_id"])
        if not course or course["instructor_id"] != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    elif role == "TeachingAssistant":
        # TA scope: must be assigned as TA on a class group of this course
        if enr.get("class_group_id"):
            cg = store.class_groups.get(enr["class_group_id"])
            if not cg or cg.get("ta_instructor_id") != user_id:
                raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the class TA")
        else:
            # if not assigned to a group, check if user is TA of any group on this course
            ok = any(
                cg.get("ta_instructor_id") == user_id
                for cg in store.class_groups.values()
                if cg["course_id"] == enr["course_id"]
            )
            if not ok:
                raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not a TA for this course")
    return success(_enrollment_view(enr))
