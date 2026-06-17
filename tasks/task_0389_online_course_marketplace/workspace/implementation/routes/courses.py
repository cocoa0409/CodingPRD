"""Course CRUD + state transitions (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, touch, require_field, as_str,
                             as_int, as_number, as_bool, paginate)
from services.course_derived import (recompute_counts, recompute_enrollment_count,
                                     recompute_ratings)
from services.serialize import view, view_list

bp = Blueprint("courses", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _refresh_course_derived(course):
    """Recompute all read-time derived fields (no version bump on GET)."""
    recompute_counts(course)
    recompute_enrollment_count(course)
    recompute_ratings(course)


@bp.route("/courses", methods=["POST"])
def create_course():
    principal = authenticate()
    require_roles(principal, "Instructor")
    body = _body()

    instructor_id = as_str(require_field(body, "instructor_id"), "instructor_id")
    title = as_str(require_field(body, "title"), "title")
    list_price_cents = as_int(require_field(body, "list_price_cents"), "list_price_cents")
    if list_price_cents < 0:
        raise err("ERR_INVALID_REQUEST", "list_price_cents must be >= 0.")

    # ownership: instructor creates courses for itself
    if principal.user_id != instructor_id:
        raise err("ERR_FORBIDDEN")
    if instructor_id not in db.instructors:
        raise err("ERR_NOT_FOUND")

    passing = body.get("passing_score_pct", 0.70)
    passing = as_number(passing, "passing_score_pct")
    if not (0.0 <= passing <= 1.0):
        raise err("ERR_INVALID_REQUEST", "passing_score_pct must be between 0.00 and 1.00.")

    refund_days = body.get("refund_window_days", 30)
    refund_days = as_int(refund_days, "refund_window_days")
    if refund_days < 0:
        raise err("ERR_INVALID_REQUEST", "refund_window_days must be >= 0.")

    drip = body.get("drip_enabled", False)
    drip = as_bool(drip, "drip_enabled")

    ceu = body.get("ceu_credits", 0.0)
    ceu = as_number(ceu, "ceu_credits")
    if ceu < 0:
        raise err("ERR_INVALID_REQUEST", "ceu_credits must be >= 0.")
    # multiples of 0.1
    if round(ceu * 10) != ceu * 10:
        raise err("ERR_INVALID_REQUEST", "ceu_credits must be a multiple of 0.1.")

    completion = body.get("completion_threshold_pct", 1.00)
    completion = as_number(completion, "completion_threshold_pct")
    if not (0.01 <= completion <= 1.00):
        raise err("ERR_INVALID_REQUEST", "completion_threshold_pct must be between 0.01 and 1.00.")

    rec = {
        "id": new_id(),
        "instructor_id": instructor_id,
        "title": title,
        "list_price_cents": list_price_cents,
        "status": "DRAFT",
        "lesson_count": 0,
        "published_lesson_count": 0,
        "passing_score_pct": passing,
        "refund_window_days": refund_days,
        "drip_enabled": drip,
        "ceu_credits": ceu,
        "completion_threshold_pct": completion,
        "enrollment_count": 0,
        "average_rating": None,
        "rating_count": 0,
    }
    stamp_create(rec)
    db.courses[rec["id"]] = rec
    return response.success(view(rec), status=201)


@bp.route("/courses/<course_id>", methods=["GET"])
def get_course(course_id):
    principal = authenticate()
    require_roles(principal, "Instructor", "Learner", "PlatformAdmin")
    course = db.courses.get(course_id)
    if course is None:
        raise err("ERR_NOT_FOUND")
    _refresh_course_derived(course)
    return response.success(view(course), status=200)


@bp.route("/courses", methods=["GET"])
def list_courses():
    principal = authenticate()
    require_roles(principal, "Instructor", "Learner", "PlatformAdmin")
    args = request.args
    instructor_id = args.get("instructor_id")
    status = args.get("status")
    items = list(db.courses.values())
    if instructor_id is not None:
        items = [c for c in items if c["instructor_id"] == instructor_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    for c in items:
        _refresh_course_derived(c)
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)


def _load_owned_course(principal, course_id):
    require_roles(principal, "Instructor")
    course = db.courses.get(course_id)
    if course is None:
        raise err("ERR_NOT_FOUND")
    if principal.user_id != course["instructor_id"]:
        raise err("ERR_FORBIDDEN")
    return course


@bp.route("/courses/<course_id>/publish", methods=["POST"])
def publish_course(course_id):
    principal = authenticate()
    course = _load_owned_course(principal, course_id)

    if course["status"] not in ("DRAFT", "UNPUBLISHED"):
        raise err("ERR_INVALID_STATE")

    lessons = [l for l in db.lessons.values() if l["course_id"] == course_id]

    if course["status"] == "DRAFT":
        # First-time publish business constraints (ERR_COURSE_NOT_PUBLISHABLE)
        if len(lessons) < 1:
            raise err("ERR_COURSE_NOT_PUBLISHABLE", "Course must have at least one lesson.")
        for l in lessons:
            if l.get("is_graded") and l.get("question_count", 0) < 1:
                raise err("ERR_COURSE_NOT_PUBLISHABLE",
                          "Every graded lesson needs question_count >= 1.")
        graded_lessons = [l for l in lessons if l.get("is_graded")]
        if graded_lessons:
            # The quiz_weight sum constraint scopes the graded-lesson denominator;
            # PRD §3.8 explicitly supports courses with no graded lessons
            # ("A course with no graded lessons auto-satisfies the score condition"),
            # so the constraint is vacuous when no graded lesson exists.
            total_weight = sum(l.get("quiz_weight", 0) for l in graded_lessons)
            if total_weight < 1:
                raise err("ERR_COURSE_NOT_PUBLISHABLE",
                          "Total quiz_weight across graded lessons must be >= 1.")
        # publish: set every lesson is_published=true
        for l in lessons:
            l["is_published"] = True
            touch(l)
        course["status"] = "PUBLISHED"
        recompute_counts(course)
        touch(course)
    else:  # UNPUBLISHED -> PUBLISHED
        published = [l for l in lessons if l.get("is_published")]
        if len(published) < 1:
            raise err("ERR_COURSE_NOT_PUBLISHABLE",
                      "Course must still have at least one published lesson.")
        course["status"] = "PUBLISHED"
        recompute_counts(course)
        touch(course)

    return response.success(view(course), status=200)


@bp.route("/courses/<course_id>/unpublish", methods=["POST"])
def unpublish_course(course_id):
    principal = authenticate()
    course = _load_owned_course(principal, course_id)
    if course["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE")
    course["status"] = "UNPUBLISHED"
    touch(course)
    return response.success(view(course), status=200)


@bp.route("/courses/<course_id>/retire", methods=["POST"])
def retire_course(course_id):
    principal = authenticate()
    course = _load_owned_course(principal, course_id)
    if course["status"] not in ("PUBLISHED", "UNPUBLISHED"):
        raise err("ERR_INVALID_STATE")
    # No ACTIVE enrollment may remain
    active = any(e for e in db.enrollments.values()
                 if e["course_id"] == course_id and e["status"] == "ACTIVE")
    if active:
        raise err("ERR_INVALID_STATE", "Course has active enrollments and cannot be retired.")

    course["status"] = "RETIRED"
    touch(course)
    # Cascade: every ACTIVE bundle whose course_ids includes this course -> RETIRED
    for bundle in db.bundles.values():
        if bundle["status"] == "ACTIVE" and course_id in bundle["course_ids"]:
            bundle["status"] = "RETIRED"
            touch(bundle)
    return response.success(view(course), status=200)
