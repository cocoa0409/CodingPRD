"""CourseOffering endpoints (PRD 3.4, 3.8).

State machine: DRAFT -> OPEN -> IN_SESSION -> GRADING -> FINALIZED, plus
DRAFT|OPEN -> CANCELLED with the conditional enrollment cascade.
"""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_GRADES_MISSING,
    ERR_INSTRUCTOR_NOT_CREDENTIALED,
    ERR_INVALID_STATE,
    ERR_OFFERING_INVALID_STATE,
    ERR_TERM_NOT_ENDED,
    ERR_TERM_NOT_OPEN,
    ERR_TERM_SCHOOL_MISMATCH,
    ERR_TERM_TYPE_MISMATCH,
)
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response, serialize_offering
from services.core import new_record, touch
from services.transitions import cancel_offering_cascade, finalize_offering_posting
from util import CLOCK
from validate import (
    get_body,
    opt_enum,
    req_int,
    req_str,
    require_body_ref,
    require_path_resource,
)

bp = Blueprint("offerings", __name__)

DELIVERY_MODES = {"HS_CAMPUS", "COLLEGE_CAMPUS", "ONLINE"}


@bp.post("/offerings")
def create_offering():
    authorized(["DualCreditAdmin"])
    body = get_body()
    course_id = req_str(body, "course_id")
    college_term_id = req_str(body, "college_term_id")
    hs_term_id = req_str(body, "hs_term_id")
    high_school_id = req_str(body, "high_school_id")
    instructor_id = req_str(body, "instructor_id")
    capacity = req_int(body, "capacity", minimum=1)
    delivery_mode = opt_enum(body, "delivery_mode", DELIVERY_MODES, default="HS_CAMPUS")

    # Priority 5: body FKs in declared input order.
    course = require_body_ref("courses", course_id, "course_id")
    college_term = require_body_ref("terms", college_term_id, "college_term_id")
    hs_term = require_body_ref("terms", hs_term_id, "hs_term_id")
    require_body_ref("high_schools", high_school_id, "high_school_id")
    require_body_ref("instructors", instructor_id, "instructor_id")

    # Priority 6: a RETIRED course cannot be used for new offerings (PRD 3.1).
    if course["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "course is RETIRED")

    # Priority 9: term type and school match.
    if college_term["institution_type"] != "COLLEGE":
        raise_error(ERR_TERM_TYPE_MISMATCH, "college_term_id must reference a COLLEGE term")
    if hs_term["institution_type"] != "HIGH_SCHOOL":
        raise_error(
            ERR_TERM_TYPE_MISMATCH, "hs_term_id must reference a HIGH_SCHOOL term"
        )
    if hs_term["high_school_id"] != high_school_id:
        raise_error(
            ERR_TERM_SCHOOL_MISMATCH,
            "hs_term.high_school_id must equal the offering's high_school_id",
        )

    rec = new_record(
        "offerings",
        {
            "course_id": course_id,
            "college_term_id": college_term_id,
            "hs_term_id": hs_term_id,
            "high_school_id": high_school_id,
            "instructor_id": instructor_id,
            "capacity": capacity,
            "delivery_mode": delivery_mode,
            "status": "DRAFT",
        },
    )
    return success_object(serialize_offering(rec), status=201)


@bp.get("/offerings")
def list_offerings():
    return list_response(
        "offerings",
        {
            "course_id": arg("course_id"),
            "high_school_id": arg("high_school_id"),
            "college_term_id": arg("college_term_id"),
            "hs_term_id": arg("hs_term_id"),
            "instructor_id": arg("instructor_id"),
            "status": arg("status"),
        },
        serializer=serialize_offering,
    )


@bp.get("/offerings/<rid>")
def get_offering(rid):
    return get_one("offerings", rid, serializer=serialize_offering)


@bp.post("/offerings/<rid>/open")
def open_offering(rid):
    authorized(["DualCreditAdmin"])
    offering = require_path_resource("offerings", rid)
    if offering["status"] != "DRAFT":
        raise_error(ERR_OFFERING_INVALID_STATE, "only a DRAFT offering can be opened")
    course = db["courses"][offering["course_id"]]
    if course["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "course is not ACTIVE")
    college_term = db["terms"][offering["college_term_id"]]
    hs_term = db["terms"][offering["hs_term_id"]]
    if college_term["status"] != "OPEN" or hs_term["status"] != "OPEN":
        raise_error(ERR_TERM_NOT_OPEN, "both referenced terms must be OPEN")
    credentialed = any(
        a["instructor_id"] == offering["instructor_id"]
        and a["course_id"] == offering["course_id"]
        and a["status"] == "APPROVED"
        for a in db["credential_applications"].values()
    )
    if not credentialed:
        raise_error(
            ERR_INSTRUCTOR_NOT_CREDENTIALED,
            "instructor holds no APPROVED credential for this course",
        )
    offering["status"] = "OPEN"
    touch(offering)
    return success_object(serialize_offering(offering))


@bp.post("/offerings/<rid>/start-session")
def start_session(rid):
    authorized(["DualCreditAdmin"])
    offering = require_path_resource("offerings", rid)
    if offering["status"] != "OPEN":
        raise_error(ERR_OFFERING_INVALID_STATE, "only an OPEN offering can start session")
    offering["status"] = "IN_SESSION"
    touch(offering)
    return success_object(serialize_offering(offering))


@bp.post("/offerings/<rid>/begin-grading")
def begin_grading(rid):
    authorized(["DualCreditAdmin"])
    offering = require_path_resource("offerings", rid)
    if offering["status"] != "IN_SESSION":
        raise_error(ERR_OFFERING_INVALID_STATE, "only an IN_SESSION offering can begin grading")
    college_term = db["terms"][offering["college_term_id"]]
    if CLOCK.now() < college_term["_end_date"]:
        raise_error(ERR_TERM_NOT_ENDED, "the college term has not ended")
    offering["status"] = "GRADING"
    touch(offering)
    return success_object(serialize_offering(offering))


@bp.post("/offerings/<rid>/finalize")
def finalize(rid):
    authorized(["CollegeRegistrar"])
    offering = require_path_resource("offerings", rid)
    if offering["status"] != "GRADING":
        raise_error(ERR_OFFERING_INVALID_STATE, "only a GRADING offering can be finalized")
    ungraded = any(
        e["offering_id"] == offering["id"]
        and e["status"] == "REGISTERED"
        and e["grade"] is None
        for e in db["enrollments"].values()
    )
    if ungraded:
        raise_error(
            ERR_GRADES_MISSING,
            "every REGISTERED enrollment must carry a grade before finalize",
        )
    offering["status"] = "FINALIZED"
    touch(offering)
    finalize_offering_posting(offering)
    return success_object(serialize_offering(offering))


@bp.post("/offerings/<rid>/cancel")
def cancel(rid):
    authorized(["DualCreditAdmin"])
    offering = require_path_resource("offerings", rid)
    if offering["status"] not in ("DRAFT", "OPEN"):
        raise_error(
            ERR_OFFERING_INVALID_STATE,
            "only a DRAFT or OPEN offering can be cancelled",
        )
    offering["status"] = "CANCELLED"
    touch(offering)
    cancel_offering_cascade(offering)
    return success_object(serialize_offering(offering))
