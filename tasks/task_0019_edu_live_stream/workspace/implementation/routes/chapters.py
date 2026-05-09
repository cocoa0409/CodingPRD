"""Chapter endpoints."""
from flask import Blueprint, request

from db import bump, make_common_fields, store
from errors import raise_api
from middleware import require_roles
from response import list_success, success
from services.lookup import get_course
from services.pagination import paginate, parse_pagination

chapters_bp = Blueprint("chapters", __name__)


@chapters_bp.route("/courses/<course_id>/chapters", methods=["POST"])
def add_chapter(course_id):
    user_id, _ = require_roles("Instructor")
    course = get_course(course_id)
    if course["instructor_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the course owner")
    if course["status"] not in ("DRAFT", "REJECTED"):
        raise_api("ERR_COURSE_NOT_UNDER_REVIEW", "Course must be DRAFT or REJECTED")
    body = request.get_json(silent=True) or {}
    title = body.get("title")
    if not title or not isinstance(title, str):
        raise_api("ERR_INVALID_PRICING", "title required")
    try:
        ordinal = int(body.get("ordinal"))
    except (TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "ordinal required")
    if ordinal < 1:
        raise_api("ERR_INVALID_PRICING", "ordinal must be >= 1")
    # Uniqueness
    for ch in store.chapters.values():
        if ch["course_id"] == course_id and int(ch["ordinal"]) == ordinal:
            raise_api("ERR_INVALID_PRICING", f"ordinal {ordinal} already used")
    try:
        dur = int(body.get("video_duration_seconds"))
    except (TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "video_duration_seconds required")
    if dur <= 0:
        raise_api("ERR_INVALID_PRICING", "video_duration_seconds must be > 0")
    required_for_completion = body.get("required_for_completion", True)
    if not isinstance(required_for_completion, bool):
        required_for_completion = True

    chapter = {
        **make_common_fields(),
        "course_id": course_id,
        "title": title,
        "ordinal": ordinal,
        "video_duration_seconds": dur,
        "required_for_completion": required_for_completion,
    }
    store.chapters[chapter["id"]] = chapter
    # bump course aggregates
    bump(course)
    return success(chapter, http_status=201)


@chapters_bp.route("/courses/<course_id>/chapters", methods=["GET"])
def list_chapters(course_id):
    require_roles("Instructor", "TeachingAssistant", "Student", "AcademicAdmin")
    get_course(course_id)
    limit, offset = parse_pagination()
    items = [c for c in store.chapters.values() if c["course_id"] == course_id]
    items.sort(key=lambda c: c["created_at"])
    page, total = paginate(items, limit, offset)
    return list_success(page, limit, offset, total)
