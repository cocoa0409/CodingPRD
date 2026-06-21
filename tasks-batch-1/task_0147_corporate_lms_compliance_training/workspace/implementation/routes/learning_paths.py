"""LearningPath + PathStep endpoints (PRD §3.2)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services.common import (
    require_body, req_field, opt_field, check_str, check_bool, check_positive_int,
    stamp_create, touch, fk_or_404, get_or_404, parse_pagination, paginate,
)

bp = Blueprint("learning_paths", __name__)


@bp.route("/learning-paths", methods=["POST"])
def create_path():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    body = require_body()
    code = check_str(req_field(body, "code"), "code")
    title = check_str(req_field(body, "title"), "title")
    enforce_sequence = opt_field(body, "enforce_sequence", True)
    check_bool(enforce_sequence, "enforce_sequence")

    for lp in db.learning_paths.values():
        if lp["code"] == code:
            raise errors.duplicate("LearningPath code already exists")

    rec = {
        "code": code,
        "title": title,
        "enforce_sequence": enforce_sequence,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.learning_paths[rec["id"]] = rec
    return object_response(ser.learning_path(rec), status=201)


@bp.route("/learning-paths/<rid>", methods=["GET"])
def get_path(rid):
    p = authenticate(require_user_id=False)
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.learning_paths, rid)
    return object_response(ser.learning_path(rec))


@bp.route("/learning-paths/<rid>/steps", methods=["POST"])
def add_step(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    path = get_or_404(db.learning_paths, rid)
    body = require_body()
    course_id = req_field(body, "course_id")
    fk_or_404(db.courses, course_id)
    sequence_index = req_field(body, "sequence_index")
    check_positive_int(sequence_index, "sequence_index")
    is_mandatory = opt_field(body, "is_mandatory", True)
    check_bool(is_mandatory, "is_mandatory")
    weight = opt_field(body, "weight", 1)
    check_positive_int(weight, "weight")

    # sequence_index unique within the path
    for s in db.path_steps.values():
        if s["learning_path_id"] == rid and s["sequence_index"] == sequence_index:
            raise errors.duplicate("sequence_index already used in this path")

    rec = {
        "learning_path_id": rid,
        "course_id": course_id,
        "sequence_index": sequence_index,
        "is_mandatory": is_mandatory,
        "weight": weight,
    }
    stamp_create(rec)
    db.path_steps[rec["id"]] = rec
    return object_response(ser.path_step(rec), status=201)


@bp.route("/learning-paths/<rid>/steps", methods=["GET"])
def list_path_steps_under_path(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    get_or_404(db.learning_paths, rid)
    limit, offset = parse_pagination()
    items = [s for s in db.path_steps.values() if s["learning_path_id"] == rid]
    page, total = paginate(items, limit, offset)
    return array_response([ser.path_step(s) for s in page], limit, offset, total)


@bp.route("/learning-paths/<rid>/publish", methods=["POST"])
def publish_path(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    path = get_or_404(db.learning_paths, rid)
    if path["status"] != "DRAFT":
        raise errors.invalid_state("Path not in DRAFT")
    steps = [s for s in db.path_steps.values() if s["learning_path_id"] == rid]
    if len(steps) == 0:
        raise errors.ApiError(errors.ERR_PATH_EMPTY, 409, "Path has no steps")
    for s in steps:
        course = db.courses.get(s["course_id"])
        if course is None or course["status"] != "PUBLISHED":
            raise errors.ApiError(errors.ERR_PATH_STEP_COURSE_NOT_PUBLISHED, 409,
                                  "Path step course not PUBLISHED")
    indices = sorted(s["sequence_index"] for s in steps)
    expected = list(range(1, len(steps) + 1))
    if indices != expected:
        raise errors.ApiError(errors.ERR_PATH_SEQUENCE_INVALID, 409,
                              "Step sequence must be contiguous 1..N")
    path["status"] = "PUBLISHED"
    touch(path)
    return object_response(ser.learning_path(path))


@bp.route("/learning-paths/<rid>/archive", methods=["POST"])
def archive_path(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    path = get_or_404(db.learning_paths, rid)
    if path["status"] != "PUBLISHED":
        raise errors.invalid_state("Path not in PUBLISHED")
    for pe in db.path_enrollments.values():
        if pe["learning_path_id"] == rid and pe["status"] in ("NOT_STARTED", "IN_PROGRESS"):
            raise errors.ApiError(errors.ERR_PATH_HAS_OPEN_ENROLLMENTS, 409,
                                  "Path has open path-enrollments")
    path["status"] = "ARCHIVED"
    touch(path)
    return object_response(ser.learning_path(path))


# --- global path-step reverse-reachability --------------------------------

@bp.route("/path-steps", methods=["GET"])
def list_path_steps():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    limit, offset = parse_pagination()
    course_id = request.args.get("course_id")
    learning_path_id = request.args.get("learning_path_id")
    items = list(db.path_steps.values())
    if course_id is not None:
        items = [s for s in items if s["course_id"] == course_id]
    if learning_path_id is not None:
        items = [s for s in items if s["learning_path_id"] == learning_path_id]
    page, total = paginate(items, limit, offset)
    return array_response([ser.path_step(s) for s in page], limit, offset, total)


@bp.route("/path-steps/<rid>", methods=["GET"])
def get_path_step(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.path_steps, rid)
    return object_response(ser.path_step(rec))
