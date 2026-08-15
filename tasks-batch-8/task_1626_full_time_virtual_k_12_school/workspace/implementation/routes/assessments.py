"""AssessmentWindow, TestSite, and ProctorAssignment endpoints
(PRD section 3.7)."""

import db
import services
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_NO_SEAT_AVAILABLE,
    ERR_ASSESSMENT_WINDOW_NOT_OPEN,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json, check_shape, pagination_params, paginate, apply_filters,
    require_fk, exist_body_fks, occ_version, parse_dt,
)

bp = make_blueprint("assessments")

WINDOW_SUBJECTS = ["ELA", "MATH", "SCIENCE"]
WINDOW_ROLES = ["PlatformAdmin", "ProctorCoordinator", "EnrollmentOfficer"]
SITE_ROLES = ["PlatformAdmin", "ProctorCoordinator"]
PROCTOR_STUDENT_ROLES = ["PlatformAdmin", "ProctorCoordinator", "EnrollmentOfficer"]


def _public_site(site):
    services.reconcile_site(site)
    return db.public(site)


# --- AssessmentWindow ---------------------------------------------------------

@bp.post("/assessment-windows")
def create_window():
    authenticate(["ProctorCoordinator", "PlatformAdmin"])
    body = body_json()
    check_shape(body, {
        "assessment_name": {"type": "string", "required": True},
        "subject": {"type": "enum", "required": True, "values": WINDOW_SUBJECTS},
        "window_start": {"type": "datetime", "required": True},
        "window_end": {"type": "datetime", "required": True},
    })
    if parse_dt(body["window_end"], "window_end") <= parse_dt(body["window_start"], "window_start"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "window_end must be strictly after window_start")
    window = db.new_entity("assessment_windows", {
        "assessment_name": body["assessment_name"],
        "subject": body["subject"],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "window_status": "SCHEDULED",
    })
    return success_obj(db.public(window), 201)


@bp.get("/assessment-windows/<wid>")
def get_window(wid):
    authenticate(WINDOW_ROLES)
    window = require_fk("assessment_windows", wid, "assessment window")
    return success_obj(db.public(window), 200)


@bp.get("/assessment-windows")
def list_windows():
    authenticate(WINDOW_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("assessment_windows"), ["window_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(w) for w in page], limit, offset, total, has_more)


# --- TestSite -----------------------------------------------------------------

@bp.post("/test-sites")
def create_site():
    authenticate(["ProctorCoordinator", "PlatformAdmin"])
    body = body_json()
    check_shape(body, {
        "site_name": {"type": "string", "required": True},
        "state_code": {"type": "state_code", "required": True},
        "seat_capacity": {"type": "integer", "required": True, "min": 1},
    })
    site = db.new_entity("test_sites", {
        "site_name": body["site_name"],
        "state_code": body["state_code"],
        "seat_capacity": body["seat_capacity"],
        "seats_booked": 0,
    })
    return success_obj(db.public(site), 201)


@bp.get("/test-sites/<tid>")
def get_site(tid):
    authenticate(SITE_ROLES)
    site = require_fk("test_sites", tid, "test site")
    return success_obj(_public_site(site), 200)


@bp.get("/test-sites")
def list_sites():
    authenticate(SITE_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("test_sites"), ["state_code"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([_public_site(s) for s in page], limit, offset, total, has_more)


# --- ProctorAssignment ---------------------------------------------------------

@bp.post("/proctor-assignments")
def create_proctor_assignment():
    authenticate(["ProctorCoordinator"])
    body = body_json()
    # Body FK existence (priority 4): all three referenced records.
    exist_body_fks(body, {
        "student_id": ("students", "student"),
        "assessment_window_id": ("assessment_windows", "assessment window"),
        "test_site_id": ("test_sites", "test site"),
    })
    student = db.get("students", body.get("student_id")) if body.get("student_id") else None
    window = (db.get("assessment_windows", body.get("assessment_window_id"))
              if body.get("assessment_window_id") else None)
    site = db.get("test_sites", body.get("test_site_id")) if body.get("test_site_id") else None
    # State admissibility (priority 5): student must be ENROLLED.
    if student is not None and student["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "proctor booking requires an ENROLLED student")
    # OCC on TestSite.version (priority 6).
    if site is not None:
        occ_version("expected_test_site_version", site["version"])(body)
    if site is not None:
        # Seat availability (priority 10) reports ahead of window timing.
        services.reconcile_site(site)
        if site["seats_booked"] + 1 > site["seat_capacity"]:
            raise ApiError(ERR_NO_SEAT_AVAILABLE, 422,
                           "no proctored seat is available at this site")
    if window is not None:
        # Bookable means SCHEDULED or OPEN; booking pre-open is allowed.
        if window["window_status"] not in ("SCHEDULED", "OPEN"):
            raise ApiError(ERR_ASSESSMENT_WINDOW_NOT_OPEN, 422,
                           "assessment window is not bookable")
    # Input shape (priority 16).
    check_shape(body, {
        "student_id": {"type": "string", "required": True},
        "assessment_window_id": {"type": "string", "required": True},
        "test_site_id": {"type": "string", "required": True},
        "expected_test_site_version": {"type": "integer", "required": True},
    })
    assignment = db.new_entity("proctor_assignments", {
        "student_id": body["student_id"],
        "assessment_window_id": body["assessment_window_id"],
        "test_site_id": body["test_site_id"],
        "assignment_status": "BOOKED",
        "booked_at": db.fmt_ts(db.now()),
        "completed_at": None,
    })
    site["seats_booked"] += 1
    db.touch(site)
    return success_obj(db.public(assignment), 201)


@bp.get("/proctor-assignments/<aid>")
def get_proctor_assignment(aid):
    authenticate(SITE_ROLES)
    assignment = require_fk("proctor_assignments", aid, "proctor assignment")
    return success_obj(db.public(assignment), 200)


@bp.get("/assessment-windows/<wid>/proctor-assignments")
def list_window_proctor_assignments(wid):
    authenticate(SITE_ROLES)
    window = require_fk("assessment_windows", wid, "assessment window")
    limit, offset = pagination_params()
    items = [a for a in db.all_of("proctor_assignments")
             if a["assessment_window_id"] == window["id"]]
    items = apply_filters(items, ["assignment_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.get("/test-sites/<tid>/proctor-assignments")
def list_site_proctor_assignments(tid):
    authenticate(SITE_ROLES)
    site = require_fk("test_sites", tid, "test site")
    limit, offset = pagination_params()
    items = [a for a in db.all_of("proctor_assignments")
             if a["test_site_id"] == site["id"]]
    items = apply_filters(items, ["assignment_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.get("/students/<sid>/proctor-assignments")
def list_student_proctor_assignments(sid):
    authenticate(PROCTOR_STUDENT_ROLES)
    student = require_fk("students", sid, "student")
    limit, offset = pagination_params()
    items = [a for a in db.all_of("proctor_assignments")
             if a["student_id"] == student["id"]]
    items = apply_filters(items, ["assignment_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.post("/proctor-assignments/<aid>/mark-completed")
def mark_proctor_completed(aid):
    authenticate(["ProctorCoordinator"])
    assignment = require_fk("proctor_assignments", aid, "proctor assignment")
    if assignment["assignment_status"] != "BOOKED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a BOOKED proctor assignment can be marked completed")
    window = db.get("assessment_windows", assignment["assessment_window_id"])
    if window is None or window["window_status"] != "OPEN":
        raise ApiError(ERR_ASSESSMENT_WINDOW_NOT_OPEN, 422,
                       "completion requires the assessment window to be OPEN")
    assignment["assignment_status"] = "COMPLETED"
    assignment["completed_at"] = db.fmt_ts(db.now())
    db.touch(assignment)
    return success_obj(db.public(assignment), 200)


@bp.post("/proctor-assignments/<aid>/cancel")
def cancel_proctor_assignment(aid):
    authenticate(["ProctorCoordinator"])
    assignment = require_fk("proctor_assignments", aid, "proctor assignment")
    if assignment["assignment_status"] != "BOOKED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a BOOKED proctor assignment can be cancelled")
    assignment["assignment_status"] = "CANCELLED"
    db.touch(assignment)
    site = db.get("test_sites", assignment["test_site_id"])
    if site is not None:
        site["seats_booked"] = max(0, site["seats_booked"] - 1)
        db.touch(site)
    return success_obj(db.public(assignment), 200)
