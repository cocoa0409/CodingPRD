"""Reviews + moderation transitions (PRD §3.10)."""
from flask import Blueprint, request

import response
from db import db, new_id
from errors import err
from middleware import authenticate, require_roles
from services.common import (stamp_create, touch, require_field, as_str, as_int,
                             paginate)
from services.course_derived import recompute_ratings_mutation
from services.serialize import view, view_list

bp = Blueprint("reviews", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


@bp.route("/reviews", methods=["POST"])
def create_review():
    principal = authenticate()
    require_roles(principal, "Learner")
    body = _body()
    enrollment_id = as_str(require_field(body, "enrollment_id"), "enrollment_id")
    stars = as_int(require_field(body, "stars"), "stars")
    review_body = as_str(require_field(body, "body"), "body")
    if not (1 <= stars <= 5):
        raise err("ERR_INVALID_REQUEST", "stars must be 1-5 inclusive.")

    enrollment = db.enrollments.get(enrollment_id)
    if enrollment is None:
        raise err("ERR_NOT_FOUND")
    # ownership: review must reference the acting learner's own enrollment
    if enrollment["learner_id"] != principal.user_id:
        raise err("ERR_FORBIDDEN")

    # eligibility (ERR_REVIEW_NOT_ELIGIBLE): enrollment COMPLETED or EXPIRED,
    # and no existing non-RETRACTED review for this enrollment.
    if enrollment["status"] not in ("COMPLETED", "EXPIRED"):
        raise err("ERR_REVIEW_NOT_ELIGIBLE", "Enrollment is not completed or expired.")
    for r in db.reviews.values():
        if r["enrollment_id"] == enrollment_id and r["status"] != "RETRACTED":
            raise err("ERR_REVIEW_NOT_ELIGIBLE", "A live review already exists for this enrollment.")

    rec = {
        "id": new_id(),
        "enrollment_id": enrollment_id,
        "course_id": enrollment["course_id"],
        "learner_id": enrollment["learner_id"],
        "stars": stars,
        "body": review_body,
        "status": "PUBLISHED",
    }
    stamp_create(rec)
    db.reviews[rec["id"]] = rec

    # recompute course rating (cascade mutation)
    course = db.courses.get(enrollment["course_id"])
    if course is not None:
        recompute_ratings_mutation(course)
    return response.success(view(rec), status=201)


@bp.route("/reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    rec = db.reviews.get(review_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return response.success(view(rec), status=200)


@bp.route("/reviews", methods=["GET"])
def list_reviews():
    principal = authenticate()
    require_roles(principal, "Learner", "Instructor", "PlatformAdmin")
    args = request.args
    items = list(db.reviews.values())
    for key in ("course_id", "enrollment_id", "learner_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    page, meta = paginate(items, args)
    return response.success(view_list(page), status=200, pagination=meta)


def _recompute_course(review):
    course = db.courses.get(review["course_id"])
    if course is not None:
        recompute_ratings_mutation(course)


@bp.route("/reviews/<review_id>/hide", methods=["POST"])
def hide_review(review_id):
    principal = authenticate()
    require_roles(principal, "PlatformAdmin")
    rec = db.reviews.get(review_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if rec["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "HIDDEN"
    touch(rec)
    _recompute_course(rec)
    return response.success(view(rec), status=200)


@bp.route("/reviews/<review_id>/unhide", methods=["POST"])
def unhide_review(review_id):
    principal = authenticate()
    require_roles(principal, "PlatformAdmin")
    rec = db.reviews.get(review_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if rec["status"] != "HIDDEN":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "PUBLISHED"
    touch(rec)
    _recompute_course(rec)
    return response.success(view(rec), status=200)


@bp.route("/reviews/<review_id>/retract", methods=["POST"])
def retract_review(review_id):
    principal = authenticate()
    require_roles(principal, "Learner")
    rec = db.reviews.get(review_id)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    # ownership: acting learner owns the enrollment the review references
    enrollment = db.enrollments.get(rec["enrollment_id"])
    owner = enrollment["learner_id"] if enrollment else rec.get("learner_id")
    if owner != principal.user_id:
        raise err("ERR_FORBIDDEN")
    if rec["status"] != "PUBLISHED":
        raise err("ERR_INVALID_STATE")
    rec["status"] = "RETRACTED"
    touch(rec)
    _recompute_course(rec)
    return response.success(view(rec), status=200)
