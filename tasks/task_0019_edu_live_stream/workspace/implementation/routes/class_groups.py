"""ClassGroup + Announcement endpoints."""
from flask import Blueprint, request

from db import bump, make_common_fields, make_immutable_fields, store
from errors import raise_api
from middleware import require_roles
from response import success
from services import audit
from services.lookup import (
    get_class_group,
    get_course,
    get_enrollment,
    get_instructor,
)

class_groups_bp = Blueprint("class_groups", __name__)


@class_groups_bp.route("/courses/<course_id>/class-groups", methods=["POST"])
def create_class_group(course_id):
    user_id, role = require_roles("Instructor", "AcademicAdmin")
    course = get_course(course_id)
    if role == "Instructor" and course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not name:
        raise_api("ERR_INVALID_PRICING", "name required")
    try:
        capacity = int(body.get("capacity"))
    except (TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "capacity required")
    if capacity <= 0:
        raise_api("ERR_INVALID_PRICING", "capacity must be > 0")
    ta_instructor_id = body.get("ta_instructor_id")
    if ta_instructor_id is not None:
        get_instructor(ta_instructor_id)
    cg = {
        **make_common_fields(),
        "course_id": course_id,
        "name": name,
        "capacity": capacity,
        "ta_instructor_id": ta_instructor_id,
        "enrolled_count": 0,
    }
    store.class_groups[cg["id"]] = cg
    return success(_cg_view(cg), http_status=201)


def _cg_view(cg):
    n = 0
    for e in store.enrollments.values():
        if e.get("class_group_id") == cg["id"] and e.get("learning_status") != "WITHDRAWN":
            n += 1
    cg["enrolled_count"] = n
    return dict(cg)


@class_groups_bp.route("/class-groups/<class_group_id>/assign-enrollment", methods=["POST"])
def assign_enrollment(class_group_id):
    user_id, role = require_roles("Instructor", "AcademicAdmin")
    cg = get_class_group(class_group_id)
    course = store.courses.get(cg["course_id"])
    if role == "Instructor":
        if not course or course["instructor_id"] != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    body = request.get_json(silent=True) or {}
    enrollment_id = body.get("enrollment_id")
    if not enrollment_id:
        raise_api("ERR_ENROLLMENT_NOT_FOUND", "enrollment_id required")
    enr = get_enrollment(enrollment_id)
    if enr["course_id"] != cg["course_id"]:
        raise_api("ERR_ENROLLMENT_NOT_FOUND", "Enrollment is not under this course")
    # Capacity check
    enrolled = sum(
        1 for e in store.enrollments.values()
        if e.get("class_group_id") == cg["id"] and e.get("learning_status") != "WITHDRAWN"
    )
    if enrolled >= int(cg["capacity"]):
        raise_api("ERR_CLASS_GROUP_FULL", "Class group is full")
    enr["class_group_id"] = cg["id"]
    bump(enr)
    audit.append(
        actor_role=role,
        actor_id=user_id,
        action="ENROLLMENT_GROUPED",
        subject_type="ENROLLMENT",
        subject_id=enr["id"],
        detail={"class_group_id": cg["id"]},
    )
    return success(dict(enr))


@class_groups_bp.route("/class-groups/<class_group_id>/announcements", methods=["POST"])
def post_announcement(class_group_id):
    user_id, role = require_roles("Instructor", "TeachingAssistant")
    cg = get_class_group(class_group_id)
    course = store.courses.get(cg["course_id"])
    if role == "Instructor":
        if not course or course["instructor_id"] != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    elif role == "TeachingAssistant":
        if cg.get("ta_instructor_id") != user_id:
            raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the class TA")
    body = request.get_json(silent=True) or {}
    text = body.get("body")
    if not text or not isinstance(text, str):
        raise_api("ERR_INVALID_PRICING", "body required")
    author_role = "INSTRUCTOR" if role == "Instructor" else "TEACHING_ASSISTANT"
    ann = {
        **make_immutable_fields(),
        "class_group_id": cg["id"],
        "course_id": cg["course_id"],
        "author_role": author_role,
        "author_id": user_id,
        "body": text,
    }
    store.announcements[ann["id"]] = ann
    return success(ann, http_status=201)
