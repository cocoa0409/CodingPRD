"""Lesson completions: record a completion / quiz attempt (PRD §3.7, §3.8)."""
from flask import Blueprint, request

import clock
import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, touch, require_field, as_str, as_int,
                             paginate, parse_dt, add_days)
from services.enrollment_logic import (score_completion, recompute_progress,
                                       try_complete, maybe_expire)
from services.serialize import view, view_list

bp = Blueprint("lesson_completions", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


@bp.route("/lesson-completions", methods=["POST"])
def create_completion():
    principal = authenticate()
    require_roles(principal, "Learner")
    body = _body()
    enrollment_id = as_str(require_field(body, "enrollment_id"), "enrollment_id")
    lesson_id = as_str(require_field(body, "lesson_id"), "lesson_id")
    correct_answers = body.get("correct_answers", 0)
    correct_answers = as_int(correct_answers, "correct_answers")
    if correct_answers < 0:
        raise err("ERR_INVALID_REQUEST", "correct_answers must be >= 0.")

    # existence (left-to-right): enrollment then lesson
    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND")
    lesson = db.lessons.get(lesson_id)
    if lesson is None:
        raise err("ERR_NOT_FOUND")

    # ownership: learner owns the enrollment
    if enrollment["learner_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN")

    course = db.courses.get(enrollment["course_id"])

    # lazy-expire the enrollment first; EXPIRED is no longer ACTIVE.
    maybe_expire(enrollment)

    # state: enrollment must be ACTIVE
    if enrollment["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment is not active.")

    # lesson must belong to enrolled course and be published
    if lesson["course_id"] != enrollment["course_id"] or not lesson.get("is_published"):
        # business constraint: lesson must belong to the enrolled course
        raise err("ERR_DUPLICATE_LESSON_COMPLETION",
                  "Lesson does not belong to the enrolled course.")

    # drip gate (priority 6) — when course.drip_enabled, lesson locked until
    # enrolled_at + drip_offset_days.
    if course["drip_enabled"]:
        enrolled_at = parse_dt(enrollment["enrolled_at"])
        unlock_at = add_days(enrolled_at, lesson.get("drip_offset_days", 0))
        if clock.now() < unlock_at:
            raise err("ERR_LESSON_LOCKED")

    # no existing completion for this (enrollment, lesson) pair
    for c in db.lesson_completions.values():
        if c["enrollment_id"] == enrollment_id and c["lesson_id"] == lesson_id:
            raise err("ERR_DUPLICATE_LESSON_COMPLETION")

    # for graded lessons, correct_answers must not exceed question_count
    if lesson.get("is_graded") and correct_answers > lesson.get("question_count", 0):
        raise err("ERR_INVALID_REQUEST", "correct_answers exceeds question_count.")

    score_pct, passed = score_completion(lesson, course, correct_answers)

    rec = {
        "id": new_id(),
        "enrollment_id": enrollment_id,
        "lesson_id": lesson_id,
        "correct_answers": correct_answers,
        "score_pct": score_pct,
        "passed": passed,
    }
    stamp_create(rec)
    db.lesson_completions[rec["id"]] = rec

    # recompute enrollment progress + weighted score (mutation of enrollment)
    recompute_progress(enrollment, course)
    touch(enrollment)

    # auto-complete check (ACTIVE -> COMPLETED); try_complete touches again on
    # transition.
    try_complete(enrollment, course)

    return response.success(view(rec), status=201)


@bp.route("/lesson-completions/<completion_id>", methods=["GET"])
def get_completion(completion_id):
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    rec = db.lesson_completions.get(completion_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return response.success(view(rec), status=200)


@bp.route("/lesson-completions", methods=["GET"])
def list_completions():
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    args = request.args
    items = list(db.lesson_completions.values())
    enrollment_id = args.get("enrollment_id")
    lesson_id = args.get("lesson_id")
    if enrollment_id is not None:
        items = [c for c in items if c["enrollment_id"] == enrollment_id]
    if lesson_id is not None:
        items = [c for c in items if c["lesson_id"] == lesson_id]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)
