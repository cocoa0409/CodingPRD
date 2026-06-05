"""Course + CoursePrerequisite endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services.common import (
    require_body, req_field, opt_field, check_str, check_enum, check_bool,
    check_positive_int, check_number, check_int, stamp_create, touch,
    fk_or_404, get_or_404, parse_pagination, paginate,
)

bp = Blueprint("courses", __name__)

CONTENT_TYPES = {"SCORM", "XAPI"}
GRADING_POLICIES = {"HIGHEST_SCORE", "LATEST_ATTEMPT"}
CEU_POLICIES = {"STANDARD", "SCORE_WEIGHTED"}


@bp.route("/courses", methods=["POST"])
def create_course():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    body = require_body()

    code = check_str(req_field(body, "code"), "code")
    title = check_str(req_field(body, "title"), "title")
    content_type = check_enum(req_field(body, "content_type"), CONTENT_TYPES, "content_type")
    passing_score = req_field(body, "passing_score")
    check_int(passing_score, "passing_score")
    if passing_score < 0 or passing_score > 100:
        raise errors.invalid_request("passing_score must be in 0..100")

    max_attempts = opt_field(body, "max_attempts", 3)
    check_positive_int(max_attempts, "max_attempts")

    ceu_credits = opt_field(body, "ceu_credits", 0)
    check_number(ceu_credits, "ceu_credits")
    if ceu_credits < 0:
        raise errors.invalid_request("ceu_credits must be non-negative")

    grading_policy = check_enum(opt_field(body, "grading_policy", "HIGHEST_SCORE"),
                                GRADING_POLICIES, "grading_policy")
    ceu_policy = check_enum(opt_field(body, "ceu_policy", "STANDARD"),
                            CEU_POLICIES, "ceu_policy")
    is_recurring = opt_field(body, "is_recurring", False)
    check_bool(is_recurring, "is_recurring")

    recurrence_months = opt_field(body, "recurrence_months", None)
    if recurrence_months is not None:
        check_positive_int(recurrence_months, "recurrence_months")

    # case-sensitive code uniqueness
    for c in db.courses.values():
        if c["code"] == code:
            raise errors.duplicate("Course code already exists")

    rec = {
        "code": code,
        "title": title,
        "content_type": content_type,
        "passing_score": passing_score,
        "max_attempts": max_attempts,
        "ceu_credits": ceu_credits,
        "grading_policy": grading_policy,
        "ceu_policy": ceu_policy,
        "is_recurring": is_recurring,
        "recurrence_months": recurrence_months,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.courses[rec["id"]] = rec
    return object_response(ser.course(rec), status=201)


@bp.route("/courses/<rid>", methods=["GET"])
def get_course(rid):
    p = authenticate(require_user_id=False)
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.courses, rid)
    return object_response(ser.course(rec))


@bp.route("/courses", methods=["GET"])
def list_courses():
    p = authenticate(require_user_id=False)
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    limit, offset = parse_pagination()
    status = request.args.get("status")
    content_type = request.args.get("content_type")
    items = list(db.courses.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if content_type is not None:
        items = [c for c in items if c["content_type"] == content_type]
    page, total = paginate(items, limit, offset)
    return array_response([ser.course(c) for c in page], limit, offset, total)


@bp.route("/courses/<rid>/publish", methods=["POST"])
def publish_course(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    rec = get_or_404(db.courses, rid)
    if rec["status"] != "DRAFT":
        raise errors.invalid_state("Course not in DRAFT")
    if rec.get("is_recurring"):
        rm = rec.get("recurrence_months")
        if not isinstance(rm, int) or isinstance(rm, bool) or rm <= 0:
            raise errors.ApiError(errors.ERR_RECURRENCE_CONFIG_INVALID, 409,
                                  "recurrence_months must be a positive integer")
    # every prerequisite course must be PUBLISHED
    for edge in db.course_prerequisites.values():
        if edge["course_id"] == rid:
            prereq = db.courses.get(edge["prerequisite_course_id"])
            if prereq is None or prereq["status"] != "PUBLISHED":
                raise errors.ApiError(errors.ERR_PREREQUISITE_NOT_PUBLISHED, 409,
                                      "Prerequisite course not PUBLISHED")
    rec["status"] = "PUBLISHED"
    touch(rec)
    return object_response(ser.course(rec))


@bp.route("/courses/<rid>/archive", methods=["POST"])
def archive_course(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    rec = get_or_404(db.courses, rid)
    if rec["status"] != "PUBLISHED":
        raise errors.invalid_state("Course not in PUBLISHED")
    for e in db.enrollments.values():
        if e["course_id"] == rid and e["status"] in ("NOT_STARTED", "IN_PROGRESS"):
            raise errors.ApiError(errors.ERR_COURSE_HAS_OPEN_ENROLLMENTS, 409,
                                  "Course has open enrollments")
    rec["status"] = "ARCHIVED"
    touch(rec)
    return object_response(ser.course(rec))


# --- prerequisites --------------------------------------------------------

@bp.route("/courses/<rid>/prerequisites", methods=["POST"])
def add_prerequisite(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    course = get_or_404(db.courses, rid)
    body = require_body()
    prerequisite_course_id = req_field(body, "prerequisite_course_id")
    fk_or_404(db.courses, prerequisite_course_id)

    # cycle check: adding edge rid -> prerequisite_course_id (rid depends on prereq).
    # A cycle exists if prerequisite_course_id can (transitively) reach rid.
    if _creates_cycle(rid, prerequisite_course_id):
        raise errors.ApiError(errors.ERR_PREREQUISITE_CYCLE, 409,
                              "Adding this prerequisite would create a cycle")

    rec = {
        "course_id": rid,
        "prerequisite_course_id": prerequisite_course_id,
    }
    stamp_create(rec)
    db.course_prerequisites[rec["id"]] = rec
    return object_response(ser.course_prerequisite(rec), status=201)


def _creates_cycle(dependent_id, prereq_id):
    """Edge means dependent depends-on prereq. Cycle if prereq reaches dependent."""
    if prereq_id == dependent_id:
        return True
    # build adjacency: course_id -> set(prerequisite_course_id) (existing edges)
    adj = {}
    for edge in db.course_prerequisites.values():
        adj.setdefault(edge["course_id"], set()).add(edge["prerequisite_course_id"])
    # also include the proposed new edge
    adj.setdefault(dependent_id, set()).add(prereq_id)
    # detect cycle reachable from dependent_id following depends-on edges
    visited = set()
    stack = [dependent_id]
    seen_start = False
    while stack:
        node = stack.pop()
        if node == dependent_id and seen_start:
            return True
        seen_start = True
        if node in visited:
            continue
        visited.add(node)
        for nxt in adj.get(node, ()):  # node depends on nxt
            if nxt == dependent_id:
                return True
            stack.append(nxt)
    return False


@bp.route("/course-prerequisites", methods=["GET"])
def list_prerequisites():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    limit, offset = parse_pagination()
    course_id = request.args.get("course_id")
    prerequisite_course_id = request.args.get("prerequisite_course_id")
    items = list(db.course_prerequisites.values())
    if course_id is not None:
        items = [c for c in items if c["course_id"] == course_id]
    if prerequisite_course_id is not None:
        items = [c for c in items if c["prerequisite_course_id"] == prerequisite_course_id]
    page, total = paginate(items, limit, offset)
    return array_response([ser.course_prerequisite(c) for c in page], limit, offset, total)


@bp.route("/course-prerequisites/<rid>", methods=["GET"])
def get_prerequisite(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.course_prerequisites, rid)
    return object_response(ser.course_prerequisite(rec))
