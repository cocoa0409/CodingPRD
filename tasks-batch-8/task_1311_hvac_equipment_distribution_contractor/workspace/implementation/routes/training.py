"""Training courses and credits."""
from datetime import timedelta
from flask import Blueprint, request

import clock
import db
from errors import ApiError, ERR_DUPLICATE, ERR_INSTRUCTOR_CONFLICT, \
    ERR_WINDOW_EXPIRED, ERR_SEAT_CAPACITY, invalid_state, invalid_request
from middleware import authenticate, authorize
from response import success
from serializers import training_course as ser_course, \
    training_credit as ser_credit
from services import core
from utils import StructErrors, check_unknown_fields, get_str, get_int, \
    get_datetime, touch, add_months
from routes.common import body, get_path, new_common, list_response

bp = Blueprint("training", __name__)

READ_ROLES = {"DistributorAdmin", "ContractorUser", "TrainingCoordinator"}


@bp.post("/training-courses")
def create_course():
    user_id, role = authenticate()
    authorize({"TrainingCoordinator"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"course_code", "title", "credit_hours",
                                "session_start", "session_end",
                                "instructor_name", "max_seats"}, struct)
    course_code = get_str(data, "course_code", struct)
    title = get_str(data, "title", struct)
    credit_hours = get_int(data, "credit_hours", struct, minimum=1)
    session_start = get_datetime(data, "session_start", struct)
    session_end = get_datetime(data, "session_end", struct)
    instructor_name = get_str(data, "instructor_name", struct)
    max_seats = get_int(data, "max_seats", struct, minimum=1)

    # Instructor conflict (priority 11): closed intervals plus a 1-day buffer —
    # a_end + 1 day must fall strictly before b_start (and vice versa).
    if instructor_name and session_start is not None and session_end is not None:
        for t in db.training_courses.values():
            if t["instructor_name"] != instructor_name:
                continue
            if t["status"] == "CANCELLED":
                continue
            a_ok = session_end + timedelta(days=1) < t["session_start"]
            b_ok = t["session_end"] + timedelta(days=1) < session_start
            if not (a_ok or b_ok):
                raise ApiError(ERR_INSTRUCTOR_CONFLICT, 422,
                               "Instructor %s has a conflicting session"
                               % instructor_name)

    # Uniqueness (priority 14).
    if isinstance(course_code, str):
        for t in db.training_courses.values():
            if t["course_code"] == course_code:
                raise ApiError(ERR_DUPLICATE, 409, "course_code already exists")
    struct.raise_if_bad()

    t = new_common()
    t.update({
        "course_code": course_code,
        "title": title,
        "credit_hours": credit_hours,
        "session_start": session_start,
        "session_end": session_end,
        "instructor_name": instructor_name,
        "max_seats": max_seats,
        "status": "SCHEDULED",
    })
    db.training_courses[t["id"]] = t
    return success(ser_course(t), 201)


@bp.get("/training-courses/<tid>")
def get_course(tid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    t = get_path(db.training_courses, tid)
    return success(ser_course(t))


@bp.get("/training-courses")
def list_courses():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"status": request.args.get("status"),
               "instructor_name": request.args.get("instructor_name")}
    return list_response(db.training_courses.values(), ser_course, filters)


@bp.patch("/training-courses/<tid>")
def patch_course(tid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin", "TrainingCoordinator"}, role)
    t = get_path(db.training_courses, tid)
    data = body()
    if t["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED course may be cancelled")
    action = data.get("action")
    if action != "CANCEL":
        raise invalid_request("action must be CANCEL")
    t["status"] = "CANCELLED"
    touch(t)
    return success(ser_course(t))


@bp.post("/training-courses/<tid>/complete")
def complete_course(tid):
    user_id, role = authenticate()
    authorize({"TrainingCoordinator"}, role)
    t = get_path(db.training_courses, tid)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"attendee_contractor_ids"}, struct)
    attendees = data.get("attendee_contractor_ids")
    if attendees is None:
        struct.add("Missing required field: attendee_contractor_ids")
        attendees = []
    elif not isinstance(attendees, list) or not all(
            isinstance(a, str) for a in attendees):
        struct.add("Field attendee_contractor_ids must be an array of strings")
        attendees = []

    # Body FK existence (priority 4).
    from routes.common import get_ref
    for a in attendees:
        get_ref(db.contractors, a, "attendee_contractor_ids")

    # From-state (priority 5).
    if t["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED course may be completed")
    # Completion allowed once the clock has reached session_end.
    if clock.now() < t["session_end"]:
        raise ApiError(ERR_WINDOW_EXPIRED, 422,
                       "Course session has not ended yet")
    if len(attendees) > t["max_seats"]:
        raise ApiError(ERR_SEAT_CAPACITY, 422,
                       "Attendee count exceeds max_seats")
    struct.raise_if_bad()

    t["status"] = "COMPLETED"
    touch(t)
    seen = set()
    for contractor_id in attendees:
        if contractor_id in seen:
            continue
        seen.add(contractor_id)
        credit = new_common()
        credit.update({
            "contractor_id": contractor_id,
            "course_id": t["id"],
            "credit_hours": t["credit_hours"],
            "earned_at": clock.now(),
            "expires_at": add_months(clock.now(), 24),
            "consumed_hours": 0,
            "status": "ACTIVE",
        })
        db.training_credits[credit["id"]] = credit
        contractor = db.contractors.get(contractor_id)
        if contractor is not None:
            core.refresh_training_balance(contractor)
    return success(ser_course(t))


@bp.get("/training-credits/<tid>")
def get_credit(tid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    t = get_path(db.training_credits, tid)
    from middleware import require_owner
    require_owner(t["contractor_id"], role, user_id)
    return success(ser_credit(t))


@bp.get("/training-credits")
def list_credits():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    filters = {"contractor_id": request.args.get("contractor_id"),
               "course_id": request.args.get("course_id"),
               "status": request.args.get("status")}
    return list_response(db.training_credits.values(), ser_credit, filters,
                         owner_field="contractor_id", role=role,
                         user_id=user_id)
