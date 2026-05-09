"""Course endpoints."""
from flask import Blueprint, request

from db import bump, make_common_fields, store
from errors import raise_api
from middleware import require_roles
from response import list_success, success
from services.course import (
    cascade_delist,
    derive_posture,
    latest_syllabus_revision_id,
    make_syllabus_revision,
    recompute_aggregates,
)
from services.lookup import get_course, get_instructor
from services.occ import check_version
from services.pagination import paginate, parse_pagination

courses_bp = Blueprint("courses", __name__)


def _validate_pricing(list_price_cents, discount_percent):
    if list_price_cents is None:
        raise_api("ERR_INVALID_PRICING", "list_price_cents required")
    try:
        price = int(list_price_cents)
    except (TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "list_price_cents must be an integer")
    if price < 0:
        raise_api("ERR_INVALID_PRICING", "list_price_cents must be >= 0")
    if discount_percent is None:
        return price, 0
    try:
        disc = int(discount_percent)
    except (TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "discount_percent must be an integer")
    if disc < 0 or disc > 80:
        raise_api("ERR_INVALID_PRICING", "discount_percent must be in [0,80]")
    return price, disc


def _course_view(course):
    """Return a view including derived aggregates."""
    recompute_aggregates(course)
    return dict(course)


@courses_bp.route("/courses", methods=["POST"])
def create_course():
    user_id, _ = require_roles("Instructor")
    body = request.get_json(silent=True) or {}
    title = body.get("title")
    if not title or not isinstance(title, str):
        raise_api("ERR_INVALID_PRICING", "title required")
    instructor_id = body.get("instructor_id")
    if not instructor_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "instructor_id required")
    # instructor must exist
    get_instructor(instructor_id)
    # Owner check: caller must be that instructor
    if instructor_id != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Caller is not the lead instructor")
    price, disc = _validate_pricing(body.get("list_price_cents"), body.get("discount_percent", 0))

    course = {
        **make_common_fields(),
        "title": title,
        "instructor_id": instructor_id,
        "list_price_cents": price,
        "discount_percent": disc,
        "status": "DRAFT",
        "posture": "RESTRICTED",
        "published_syllabus_revision_id": None,
        "total_chapters": 0,
        "total_video_seconds": 0,
        "enrollment_count": 0,
    }
    store.courses[course["id"]] = course
    return success(_course_view(course), http_status=201)


@courses_bp.route("/courses", methods=["GET"])
def list_courses():
    require_roles("Instructor", "TeachingAssistant", "Student", "AcademicAdmin")
    limit, offset = parse_pagination()
    items = list(store.courses.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return list_success([_course_view(c) for c in page], limit, offset, total)


@courses_bp.route("/courses/<course_id>", methods=["GET"])
def get_one_course(course_id):
    require_roles("Instructor", "TeachingAssistant", "Student", "AcademicAdmin")
    course = get_course(course_id)
    return success(_course_view(course))


@courses_bp.route("/courses/<course_id>", methods=["PATCH"])
def update_course(course_id):
    user_id, _ = require_roles("Instructor")
    course = get_course(course_id)
    if course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    body = request.get_json(silent=True) or {}
    check_version(course, body)
    if course["status"] not in ("DRAFT", "REJECTED"):
        raise_api("ERR_COURSE_NOT_REJECTED", "Course must be DRAFT or REJECTED to update")

    new_price = course["list_price_cents"]
    new_disc = course["discount_percent"]
    if "list_price_cents" in body and body["list_price_cents"] is not None:
        try:
            new_price = int(body["list_price_cents"])
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_PRICING", "list_price_cents must be integer")
        if new_price < 0:
            raise_api("ERR_INVALID_PRICING", "list_price_cents must be >= 0")
    if "discount_percent" in body and body["discount_percent"] is not None:
        try:
            new_disc = int(body["discount_percent"])
        except (TypeError, ValueError):
            raise_api("ERR_INVALID_PRICING", "discount_percent must be integer")
        if new_disc < 0 or new_disc > 80:
            raise_api("ERR_INVALID_PRICING", "discount_percent in [0,80]")

    if "title" in body and body["title"] is not None:
        if not isinstance(body["title"], str) or not body["title"]:
            raise_api("ERR_INVALID_PRICING", "title must be a non-empty string")
        course["title"] = body["title"]
    course["list_price_cents"] = new_price
    course["discount_percent"] = new_disc
    bump(course)
    return success(_course_view(course))


@courses_bp.route("/courses/<course_id>/submit-for-review", methods=["POST"])
def submit_for_review(course_id):
    user_id, _ = require_roles("Instructor")
    course = get_course(course_id)
    if course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    if course["status"] != "DRAFT":
        raise_api("ERR_COURSE_NOT_UNDER_REVIEW", "Course must be DRAFT to submit for review")
    required_chapters = [c for c in store.chapters.values()
                         if c["course_id"] == course_id and c.get("required_for_completion", True)]
    if not required_chapters:
        raise_api("ERR_COURSE_NO_CHAPTERS", "At least one required chapter is needed")
    # validate pricing
    if int(course["list_price_cents"]) < 0 or not (0 <= int(course["discount_percent"]) <= 80):
        raise_api("ERR_INVALID_PRICING", "Invalid pricing")
    course["status"] = "UNDER_REVIEW"
    course["posture"] = derive_posture(course["status"])
    bump(course)
    make_syllabus_revision(course)
    return success(_course_view(course))


@courses_bp.route("/courses/<course_id>/approve", methods=["POST"])
def approve_course(course_id):
    require_roles("AcademicAdmin")
    course = get_course(course_id)
    if course["status"] != "UNDER_REVIEW":
        raise_api("ERR_COURSE_NOT_UNDER_REVIEW", "Course must be UNDER_REVIEW")
    course["status"] = "PUBLISHED"
    course["posture"] = derive_posture(course["status"])
    course["published_syllabus_revision_id"] = latest_syllabus_revision_id(course_id)
    bump(course)
    return success(_course_view(course))


@courses_bp.route("/courses/<course_id>/reject", methods=["POST"])
def reject_course(course_id):
    require_roles("AcademicAdmin")
    course = get_course(course_id)
    if course["status"] != "UNDER_REVIEW":
        raise_api("ERR_COURSE_NOT_UNDER_REVIEW", "Course must be UNDER_REVIEW")
    course["status"] = "REJECTED"
    course["posture"] = derive_posture(course["status"])
    bump(course)
    return success(_course_view(course))


@courses_bp.route("/courses/<course_id>/return-to-draft", methods=["POST"])
def return_to_draft(course_id):
    user_id, _ = require_roles("Instructor")
    course = get_course(course_id)
    if course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    if course["status"] != "REJECTED":
        raise_api("ERR_COURSE_NOT_REJECTED", "Course must be REJECTED")
    course["status"] = "DRAFT"
    course["posture"] = derive_posture(course["status"])
    bump(course)
    return success(_course_view(course))


@courses_bp.route("/courses/<course_id>/delist", methods=["POST"])
def delist_course(course_id):
    require_roles("AcademicAdmin")
    course = get_course(course_id)
    if course["status"] != "PUBLISHED":
        raise_api("ERR_COURSE_NOT_PUBLISHED", "Course must be PUBLISHED to delist")
    course["status"] = "DELISTED"
    course["posture"] = derive_posture(course["status"])
    bump(course)
    cascade_delist(course)
    return success(_course_view(course))


@courses_bp.route("/courses/<course_id>/syllabus-revisions", methods=["GET"])
def list_syllabus_revisions(course_id):
    require_roles("Instructor", "TeachingAssistant", "Student", "AcademicAdmin")
    get_course(course_id)
    limit, offset = parse_pagination()
    items = [s for s in store.syllabus_revisions.values() if s["course_id"] == course_id]
    items.sort(key=lambda s: s["created_at"])
    page, total = paginate(items, limit, offset)
    return list_success(page, limit, offset, total)
