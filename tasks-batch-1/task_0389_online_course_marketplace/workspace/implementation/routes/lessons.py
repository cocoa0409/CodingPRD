"""Lesson CRUD (PRD §3.2)."""
from flask import Blueprint, request

import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, touch, require_field, as_str,
                             as_int, as_bool, paginate)
from services.course_derived import recompute_counts
from services.serialize import view, view_list

bp = Blueprint("lessons", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


@bp.route("/lessons", methods=["POST"])
def create_lesson():
    principal = authenticate()
    require_roles(principal, "Instructor")
    body = _body()

    course_id = as_str(require_field(body, "course_id"), "course_id")
    title = as_str(require_field(body, "title"), "title")
    order_index = as_int(require_field(body, "order_index"), "order_index")
    if order_index < 1:
        raise err("ERR_INVALID_REQUEST", "order_index must be a 1-based positive integer.")

    course = db.courses.get(course_id)
    if course is None:
        raise err("ERR_NOT_FOUND")
    # ownership
    if principal.user_id != course["instructor_id"]:
        raise err("ERR_FORBIDDEN")
    # may only be added while DRAFT or UNPUBLISHED
    if course["status"] not in ("DRAFT", "UNPUBLISHED"):
        raise err("ERR_INVALID_STATE", "Lessons may only be added to DRAFT or UNPUBLISHED courses.")

    is_graded = as_bool(body.get("is_graded", False), "is_graded")
    quiz_weight = as_int(body.get("quiz_weight", 0), "quiz_weight")
    if quiz_weight < 0:
        raise err("ERR_INVALID_REQUEST", "quiz_weight must be >= 0.")
    question_count = as_int(body.get("question_count", 0), "question_count")
    if question_count < 0:
        raise err("ERR_INVALID_REQUEST", "question_count must be >= 0.")
    drip_offset = as_int(body.get("drip_offset_days", 0), "drip_offset_days")
    if drip_offset < 0:
        raise err("ERR_INVALID_REQUEST", "drip_offset_days must be >= 0.")

    if is_graded and question_count < 1:
        raise err("ERR_INVALID_REQUEST", "A graded lesson needs question_count >= 1.")

    # order_index unique per course -> ERR_DUPLICATE_LESSON_COMPLETION (409)
    for l in db.lessons.values():
        if l["course_id"] == course_id and l["order_index"] == order_index:
            raise err("ERR_DUPLICATE_LESSON_COMPLETION",
                      "order_index already used within this course.")

    rec = {
        "id": new_id(),
        "course_id": course_id,
        "title": title,
        "order_index": order_index,
        "is_graded": is_graded,
        "quiz_weight": quiz_weight,
        "question_count": question_count,
        "drip_offset_days": drip_offset,
        "is_published": False,
    }
    stamp_create(rec)
    db.lessons[rec["id"]] = rec

    # recompute Course.lesson_count (mutation of the course)
    recompute_counts(course)
    touch(course)
    return response.success(view(rec), status=201)


@bp.route("/lessons/<lesson_id>", methods=["GET"])
def get_lesson(lesson_id):
    principal = authenticate()
    require_roles(principal, "Instructor", "Learner", "PlatformAdmin")
    lesson = db.lessons.get(lesson_id)
    if lesson is None:
        raise err("ERR_NOT_FOUND")
    return response.success(view(lesson), status=200)


@bp.route("/lessons", methods=["GET"])
def list_lessons():
    principal = authenticate()
    require_roles(principal, "Instructor", "Learner", "PlatformAdmin")
    args = request.args
    course_id = args.get("course_id")
    items = list(db.lessons.values())
    if course_id is not None:
        items = [l for l in items if l["course_id"] == course_id]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)
