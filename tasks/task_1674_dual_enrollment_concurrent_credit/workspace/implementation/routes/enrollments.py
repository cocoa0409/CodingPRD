"""Enrollment endpoints (PRD 3.5, 3.6, 3.8, 3.9).

State machine:
  PENDING_VERIFICATION -> REGISTERED (confirm with a free seat, +Invoice)
  PENDING_VERIFICATION -> WAITLISTED (confirm with zero free seats, +waitlist_seq)
  PENDING_VERIFICATION -> CANCELLED (offering cancel cascade)
  REGISTERED -> DROPPED (drop / admin drop), WITHDRAWN (withdraw), COMPLETED (finalize)
  WAITLISTED -> REGISTERED (promotion), CANCELLED (cancel-waitlist / cascade),
                EXPIRED (term close cascade)
  WITHDRAWN -> REGISTERED (reinstate, OCC-guarded, new Invoice)

The confirm and reinstate writes carry the two OCC rules
(expected_offering_version vs CourseOffering.version -> ERR_STALE_VERSION 412).
"""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ADD_WINDOW_CLOSED,
    ERR_DROP_WINDOW_CLOSED,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_ENROLLMENT_INVALID_STATE,
    ERR_NO_FUNDING_AGREEMENT,
    ERR_NO_SEATS_AVAILABLE,
    ERR_NOT_OFFERING_INSTRUCTOR,
    ERR_OFFERING_INVALID_STATE,
    ERR_PREREQUISITE_NOT_MET,
    ERR_SCHOOL_SUSPENDED,
    ERR_STALE_VERSION,
    ERR_STUDENT_NOT_ELIGIBLE,
    ERR_TERM_NOT_OPEN,
    ERR_VALIDATION,
    ERR_WITHDRAW_WINDOW_CLOSED,
)
from middleware import ANY_ROLE, authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calculations import (
    DROP_REFUND_PCT,
    check_placement,
    create_invoice,
    effective_add_deadline,
    effective_drop_deadline,
    effective_withdraw_deadline,
    find_funding_agreement,
    next_waitlist_seq,
    prerequisites_satisfied,
    seats_available,
    transfer_evaluation,
    withdraw_refund_pct,
)
from services.core import new_record, public, touch
from services.transitions import release_seat_and_promote, settle_enrollment_invoice
from util import CLOCK
from validate import (
    get_body,
    req_enum,
    req_int,
    req_str,
    require_body_ref,
    require_path_resource,
)

bp = Blueprint("enrollments", __name__)

ACTIVE_ENROLLMENT_STATUSES = {"PENDING_VERIFICATION", "REGISTERED", "WAITLISTED"}
SUBMITTABLE_GRADES = {"A", "B", "C", "D", "F"}  # W is system-set by withdraw only


@bp.post("/enrollments")
def create_enrollment():
    authorized(["HsCoordinator"])
    body = get_body()
    student_id = req_str(body, "student_id")
    offering_id = req_str(body, "offering_id")
    # Priority 5: body FKs in declared input order.
    require_body_ref("students", student_id, "student_id")
    offering = require_body_ref("offerings", offering_id, "offering_id")
    # Priority 6: enrollment may only be created against an OPEN offering.
    if offering["status"] != "OPEN":
        raise_error(
            ERR_OFFERING_INVALID_STATE,
            "enrollments can only be created against an OPEN offering",
        )
    # Priority 15: no duplicate live enrollment for (student, offering).
    for e in db["enrollments"].values():
        if (
            e["student_id"] == student_id
            and e["offering_id"] == offering_id
            and e["status"] in ACTIVE_ENROLLMENT_STATUSES
        ):
            raise_error(ERR_DUPLICATE_ENROLLMENT, "an active enrollment already exists")
    rec = new_record(
        "enrollments",
        {
            "student_id": student_id,
            "offering_id": offering_id,
            "status": "PENDING_VERIFICATION",
            "grade": None,
            "waitlist_seq": None,
            "withdrawn_at": None,
        },
    )
    rec["_withdrawn_at"] = None
    return success_object(public(rec), status=201)


@bp.get("/enrollments")
def list_enrollments():
    return list_response(
        "enrollments",
        {
            "student_id": arg("student_id"),
            "offering_id": arg("offering_id"),
            "status": arg("status"),
        },
    )


@bp.get("/enrollments/<rid>")
def get_enrollment(rid):
    return get_one("enrollments", rid)


@bp.post("/enrollments/<rid>/confirm")
def confirm_enrollment(rid):
    authorized(["HsCoordinator"])
    body = get_body()
    expected_offering_version = req_int(body, "expected_offering_version")
    enrollment = require_path_resource("enrollments", rid)
    offering = db["offerings"][enrollment["offering_id"]]
    student = db["students"][enrollment["student_id"]]

    # Priority 6: enrollment state, then OCC, then offering state.
    if enrollment["status"] != "PENDING_VERIFICATION":
        raise_error(
            ERR_ENROLLMENT_INVALID_STATE,
            "only a PENDING_VERIFICATION enrollment can be confirmed",
        )
    if expected_offering_version != offering["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_offering_version does not match the offering's current version",
        )
    if offering["status"] != "OPEN":
        raise_error(ERR_OFFERING_INVALID_STATE, "offering is not OPEN")

    # Priority 7: business safety.
    if student["status"] != "ELIGIBLE" or student["grade_level"] < 11:
        raise_error(
            ERR_STUDENT_NOT_ELIGIBLE,
            "student must be ELIGIBLE with grade_level >= 11",
        )
    school = db["high_schools"][student["high_school_id"]]
    if school["status"] != "ACTIVE":
        raise_error(ERR_SCHOOL_SUSPENDED, "the student's high school is SUSPENDED")

    # Priority 8: the add window (earlier of the two calendars, inclusive).
    now = CLOCK.now()
    if now > effective_add_deadline(offering):
        raise_error(ERR_ADD_WINDOW_CLOSED, "the effective add deadline has passed")

    # Priority 9: both terms OPEN.
    college_term = db["terms"][offering["college_term_id"]]
    hs_term = db["terms"][offering["hs_term_id"]]
    if college_term["status"] != "OPEN" or hs_term["status"] != "OPEN":
        raise_error(ERR_TERM_NOT_OPEN, "both referenced terms must be OPEN")

    course = db["courses"][offering["course_id"]]
    # Priority 10: prerequisite satisfaction.
    if not prerequisites_satisfied(student["id"], course["id"]):
        raise_error(ERR_PREREQUISITE_NOT_MET, "a course prerequisite is not satisfied")
    # Priorities 11-12: placement presence, then score sufficiency.
    check_placement(student["id"], course, now)
    # Priority 13: funding agreement existence.
    if find_funding_agreement(offering["high_school_id"], offering["college_term_id"]) is None:
        raise_error(
            ERR_NO_FUNDING_AGREEMENT,
            "no funding agreement for (high_school_id, college_term_id)",
        )

    # Seat branch: a free seat registers; a full section waitlists (the same
    # request lands in WAITLISTED instead of failing).
    if seats_available(offering) >= 1:
        enrollment["status"] = "REGISTERED"
        touch(enrollment)
        touch(offering)  # seat consumed: CourseOffering.version += 1
        create_invoice(enrollment, offering)
    else:
        enrollment["status"] = "WAITLISTED"
        enrollment["waitlist_seq"] = next_waitlist_seq(offering["id"])
        touch(enrollment)  # no seat moved: offering version unchanged
    return success_object(public(enrollment))


@bp.post("/enrollments/<rid>/drop")
def drop_enrollment(rid):
    authorized(["HsCoordinator"])
    enrollment = require_path_resource("enrollments", rid)
    if enrollment["status"] != "REGISTERED":
        raise_error(ERR_ENROLLMENT_INVALID_STATE, "only a REGISTERED enrollment can drop")
    offering = db["offerings"][enrollment["offering_id"]]
    now = CLOCK.now()
    if now > effective_drop_deadline(offering):
        raise_error(ERR_DROP_WINDOW_CLOSED, "the effective drop deadline has passed")
    enrollment["status"] = "DROPPED"
    touch(enrollment)
    # refund_settlement estimate variant at 100 pct (invoice voided).
    settle_enrollment_invoice(enrollment, DROP_REFUND_PCT)
    # Seat release bumps the offering version; waitlist promotion may follow.
    release_seat_and_promote(offering)
    return success_object(public(enrollment))


@bp.post("/enrollments/<rid>/withdraw")
def withdraw_enrollment(rid):
    authorized(["HsCoordinator"])
    enrollment = require_path_resource("enrollments", rid)
    if enrollment["status"] != "REGISTERED":
        raise_error(
            ERR_ENROLLMENT_INVALID_STATE, "only a REGISTERED enrollment can withdraw"
        )
    offering = db["offerings"][enrollment["offering_id"]]
    now = CLOCK.now()
    # While the drop window is still open, drop must be used instead.
    if now <= effective_drop_deadline(offering):
        raise_error(
            ERR_ENROLLMENT_INVALID_STATE,
            "the drop window is still open; drop must be used",
        )
    if now > effective_withdraw_deadline(offering):
        raise_error(
            ERR_WITHDRAW_WINDOW_CLOSED, "the effective withdraw deadline has passed"
        )
    enrollment["status"] = "WITHDRAWN"
    enrollment["grade"] = "W"
    enrollment["withdrawn_at"] = CLOCK.now_iso()  # logical-clock timestamp
    enrollment["_withdrawn_at"] = now
    touch(enrollment)
    # refund_percentage: 50 iff now <= college_term.drop_deadline else 0.
    settle_enrollment_invoice(enrollment, withdraw_refund_pct(offering, now))
    release_seat_and_promote(offering)
    return success_object(public(enrollment))


@bp.post("/enrollments/<rid>/reinstate")
def reinstate_enrollment(rid):
    authorized(["CollegeRegistrar"])
    body = get_body()
    expected_offering_version = req_int(body, "expected_offering_version")
    enrollment = require_path_resource("enrollments", rid)
    offering = db["offerings"][enrollment["offering_id"]]

    # Priority 6: enrollment state, then OCC, then offering state.
    if enrollment["status"] != "WITHDRAWN":
        raise_error(
            ERR_ENROLLMENT_INVALID_STATE, "only a WITHDRAWN enrollment can be reinstated"
        )
    if expected_offering_version != offering["version"]:
        raise_error(
            ERR_STALE_VERSION,
            "expected_offering_version does not match the offering's current version",
        )
    if offering["status"] not in ("OPEN", "IN_SESSION"):
        raise_error(ERR_OFFERING_INVALID_STATE, "offering is not OPEN or IN_SESSION")

    # Priority 8: at or before the college term's end.
    college_term = db["terms"][offering["college_term_id"]]
    if CLOCK.now() > college_term["_end_date"]:
        raise_error(ERR_WITHDRAW_WINDOW_CLOSED, "the college term has ended")

    # Priority 16: a free seat must exist.
    if seats_available(offering) < 1:
        raise_error(ERR_NO_SEATS_AVAILABLE, "no seats available on the offering")

    enrollment["status"] = "REGISTERED"
    enrollment["grade"] = None
    enrollment["withdrawn_at"] = None
    enrollment["_withdrawn_at"] = None
    touch(enrollment)
    touch(offering)  # seat consumed: CourseOffering.version += 1
    # A NEW invoice; the previous invoice keeps its own state and refund fields.
    create_invoice(enrollment, offering)
    return success_object(public(enrollment))


@bp.post("/enrollments/<rid>/cancel-waitlist")
def cancel_waitlist(rid):
    authorized(["HsCoordinator"])
    enrollment = require_path_resource("enrollments", rid)
    if enrollment["status"] != "WAITLISTED":
        raise_error(
            ERR_ENROLLMENT_INVALID_STATE,
            "only a WAITLISTED enrollment can be cancelled from the waitlist",
        )
    enrollment["status"] = "CANCELLED"
    touch(enrollment)
    return success_object(public(enrollment))


@bp.post("/enrollments/<rid>/submit-grade")
def submit_grade(rid):
    caller = authorized(["Instructor"])
    enrollment = require_path_resource("enrollments", rid)
    offering = db["offerings"][enrollment["offering_id"]]
    # Priority 3: only the offering's instructor of record.
    if offering["instructor_id"] != caller.user_id:
        raise_error(
            ERR_NOT_OFFERING_INSTRUCTOR,
            "caller is not the offering's instructor of record",
        )
    grade = req_enum(get_body(), "grade", SUBMITTABLE_GRADES)
    if enrollment["status"] != "REGISTERED":
        raise_error(
            ERR_ENROLLMENT_INVALID_STATE,
            "grades may only be recorded on REGISTERED enrollments",
        )
    if offering["status"] != "GRADING":
        raise_error(ERR_OFFERING_INVALID_STATE, "offering is not in GRADING")
    enrollment["grade"] = grade
    touch(enrollment)
    return success_object(public(enrollment))


@bp.get("/enrollments/<rid>/transfer-evaluation")
def transfer_eval(rid):
    authorized(ANY_ROLE)
    target = request.args.get("target_institution")
    if target is None or target.strip() == "":
        raise_error(ERR_VALIDATION, "target_institution query parameter is required")
    enrollment = require_path_resource("enrollments", rid)
    return success_object(transfer_evaluation(enrollment, target))
