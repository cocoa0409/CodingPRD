"""Qualification endpoints (PRD §3.2): grant, list/get with lazy expiry,
revoke."""

import db
from errors import (
    ApiError,
    ERR_QUALIFICATION_NOT_FOUND,
    ERR_FACULTY_NOT_FOUND,
    ERR_COURSE_NOT_FOUND,
    ERR_DUPLICATE_QUALIFICATION,
    ERR_INVALID_QUALIFICATION_TRANSITION,
)
from middleware import authenticate, ALL_ROLES, CHAIR
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters
from services import effective_qual_status, qual_public

bp = make_blueprint("qualifications")

QUAL_STATUSES = ["ACTIVE", "REVOKED", "EXPIRED"]


def require_qualification(qualification_id):
    qual = db.get("qualifications", qualification_id)
    if qual is None:
        raise ApiError(ERR_QUALIFICATION_NOT_FOUND, 404, "qualification not found")
    return qual


@bp.post("/qualifications")
def create_qualification():
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {
        "faculty_id": {"type": "string", "required": True},
        "course_id": {"type": "string", "required": True},
        "expires_on": {"type": "date", "required": True},
    })
    # Body FK existence in declared input order: faculty_id before course_id.
    if db.get("faculty_members", body["faculty_id"]) is None:
        raise ApiError(ERR_FACULTY_NOT_FOUND, 404, "faculty member not found")
    if db.get("courses", body["course_id"]) is None:
        raise ApiError(ERR_COURSE_NOT_FOUND, 404, "course not found")
    # At most one ACTIVE qualification per (faculty, course); lazy expiry is
    # applied before the duplicate check.
    for q in db.all_of("qualifications"):
        if (q["faculty_id"] == body["faculty_id"] and q["course_id"] == body["course_id"]
                and effective_qual_status(q) == "ACTIVE"):
            raise ApiError(ERR_DUPLICATE_QUALIFICATION, 409,
                           "an ACTIVE qualification already exists for this faculty and course")
    qual = db.new_entity("qualifications", {
        "faculty_id": body["faculty_id"],
        "course_id": body["course_id"],
        "expires_on": body["expires_on"],
        "status": "ACTIVE",
    })
    return success_obj(qual_public(qual), 201)


@bp.get("/qualifications")
def list_qualifications():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(
        db.all_of("qualifications"),
        ["faculty_id", "course_id", "status"],
        key=qual_public,  # filter against the lazily-derived effective status
    )
    page, total, has_more = paginate(items, limit, offset)
    return success_list([qual_public(q) for q in page], limit, offset, total, has_more)


@bp.get("/qualifications/<qualificationId>")
def get_qualification(qualificationId):
    authenticate(ALL_ROLES)
    return success_obj(qual_public(require_qualification(qualificationId)), 200)


@bp.patch("/qualifications/<qualificationId>")
def patch_qualification(qualificationId):
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {"status": {"type": "enum", "values": QUAL_STATUSES, "required": True}})
    qual = require_qualification(qualificationId)
    # REVOKED and (lazily) EXPIRED are terminal; the only accepted target is
    # REVOKED — anything else is an invalid transition.
    if effective_qual_status(qual) != "ACTIVE":
        raise ApiError(ERR_INVALID_QUALIFICATION_TRANSITION, 409, "qualification is already terminal")
    if body["status"] != "REVOKED":
        raise ApiError(ERR_INVALID_QUALIFICATION_TRANSITION, 409,
                       "the only permitted qualification status edit is REVOKED")
    qual["status"] = "REVOKED"
    db.touch(qual)
    return success_obj(qual_public(qual), 200)
