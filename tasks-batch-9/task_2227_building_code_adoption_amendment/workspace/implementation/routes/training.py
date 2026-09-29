"""Training rollout: sessions, enrollments, attendance (PRD 3.9)."""
from flask import Blueprint

import clock
import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_str, paged
from services import cascades, derive, lookup, serialize

bp = Blueprint("training", __name__)

_SESSION_TRANSITIONS = {
    ("SCHEDULED", "ENROLLMENT_OPEN"),
    ("ENROLLMENT_OPEN", "ENROLLMENT_CLOSED"),
    ("SCHEDULED", "CANCELLED"),
    ("ENROLLMENT_OPEN", "CANCELLED"),
    ("ENROLLMENT_CLOSED", "CANCELLED"),
}


# ------------------------------------------------------------------ sessions
@bp.post("/training-sessions")
def create_training_session():
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    adoption_rule_id = validate.req_string(body, "adoption_rule_id")
    host_jurisdiction_id = validate.req_string(body, "host_jurisdiction_id")
    discipline = validate.req_enum(body, "discipline", config.DISCIPLINES)
    audience = validate.req_enum(body, "audience", config.AUDIENCES)
    seat_capacity = validate.req_int(body, "seat_capacity", 1)
    starts_at = validate.req_dt(body, "starts_at")
    ends_at = validate.req_dt(body, "ends_at")
    if ends_at <= starts_at:
        raise validate.bad_request("ends_at must be later than starts_at.")

    rule = lookup.adoption_rule(adoption_rule_id)
    host = lookup.jurisdiction(host_jurisdiction_id)

    committed = seat_capacity
    for other in derive.children(db.training_sessions, "host_jurisdiction_id", host["id"]):
        if other["status"] == "CANCELLED":
            continue
        if starts_at < other["ends_at"] and other["starts_at"] < ends_at:
            committed += other["seat_capacity"]
    if committed > host["host_seat_capacity"]:
        raise ApiError("ERR_HOST_CAPACITY_EXCEEDED")

    record = db.new_record({
        "adoption_rule_id": rule["id"],
        "host_jurisdiction_id": host["id"],
        "discipline": discipline,
        "audience": audience,
        "seat_capacity": seat_capacity,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "cancellation_reason": None,
        "status": "SCHEDULED",
    })
    db.training_sessions[record["id"]] = record
    return response.object_response(serialize.training_session(record), 201)


@bp.get("/training-sessions")
def list_training_sessions():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.training_sessions.values()), {
        "status": ("status", as_str),
        "adoption_rule_id": ("adoption_rule_id", as_str),
        "host_jurisdiction_id": ("host_jurisdiction_id", as_str),
        "discipline": ("discipline", as_str),
        "audience": ("audience", as_str),
    })
    return paged(rows, serialize.training_session, limit, offset)


@bp.get("/training-sessions/<training_session_id>")
def get_training_session(training_session_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.training_session(training_session_id)
    return response.object_response(serialize.training_session(record))


@bp.post("/training-sessions/<training_session_id>/status")
def set_training_session_status(training_session_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    to_status = validate.req_enum(body, "to_status", config.SESSION_STATUSES)
    cancellation_reason = validate.opt_string(body, "cancellation_reason")
    session = lookup.training_session(training_session_id)

    if (session["status"], to_status) not in _SESSION_TRANSITIONS:
        raise ApiError("ERR_SESSION_STATE_INVALID")

    if to_status == "ENROLLMENT_OPEN":
        rule = db.adoption_rules.get(session["adoption_rule_id"])
        if rule is None or rule["status"] not in ("PUBLISHED", "EFFECTIVE"):
            raise ApiError("ERR_ADOPTION_RULE_NOT_IN_FORCE")
        session["status"] = "ENROLLMENT_OPEN"
        db.touch(session)
    elif to_status == "ENROLLMENT_CLOSED":
        session["status"] = "ENROLLMENT_CLOSED"
        db.touch(session)
    else:
        cascades.cancel_session(session, cancellation_reason)

    return response.object_response(serialize.training_session(session))


# ------------------------------------------------------------------ enrollments
@bp.post("/training-sessions/<training_session_id>/enrollments")
def create_enrollment(training_session_id):
    user_id, role = middleware.require((config.ROLE_COUNCIL_ADMIN,
                                        config.ROLE_JURISDICTION_OFFICIAL))
    middleware.resolve_identity(user_id, role)
    body = validate.body()
    jurisdiction_id = validate.req_string(body, "jurisdiction_id")
    attendee_name = validate.req_string(body, "attendee_name")
    attendee_role = validate.req_enum(body, "attendee_role", config.ATTENDEE_ROLES)

    session = lookup.training_session(training_session_id)
    jurisdiction = lookup.jurisdiction(jurisdiction_id)

    if role == config.ROLE_JURISDICTION_OFFICIAL and jurisdiction["id"] != user_id:
        raise ApiError("ERR_JURISDICTION_MISMATCH")

    if session["status"] != "ENROLLMENT_OPEN":
        raise ApiError("ERR_SESSION_STATE_INVALID")

    for existing in derive.enrollments_of_session(session["id"]):
        if existing["attendee_name"] == attendee_name and existing["status"] != "CANCELLED":
            raise ApiError("ERR_DUPLICATE_ENROLLMENT")

    if derive.session_seats_available(session) <= 0:
        raise ApiError("ERR_SESSION_FULL")

    record = db.new_record({
        "training_session_id": session["id"],
        "jurisdiction_id": jurisdiction["id"],
        "attendee_name": attendee_name,
        "attendee_role": attendee_role,
        "enrolled_by_user_id": user_id,
        "status": "ENROLLED",
    })
    db.training_enrollments[record["id"]] = record
    return response.object_response(serialize.training_enrollment(record), 201)


@bp.get("/training-sessions/<training_session_id>/enrollments")
def list_session_enrollments(training_session_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    session = lookup.training_session(training_session_id)
    rows = derive.enrollments_of_session(session["id"])
    return paged(rows, serialize.training_enrollment, limit, offset)


@bp.get("/training-enrollments")
def list_enrollments():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.training_enrollments.values()), {
        "status": ("status", as_str),
        "training_session_id": ("training_session_id", as_str),
        "jurisdiction_id": ("jurisdiction_id", as_str),
        "attendee_role": ("attendee_role", as_str),
    })
    return paged(rows, serialize.training_enrollment, limit, offset)


@bp.get("/training-enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.enrollment(enrollment_id)
    return response.object_response(serialize.training_enrollment(record))


@bp.post("/training-enrollments/<enrollment_id>/cancel")
def cancel_enrollment(enrollment_id):
    user_id, role = middleware.require((config.ROLE_COUNCIL_ADMIN,
                                        config.ROLE_JURISDICTION_OFFICIAL))
    middleware.resolve_identity(user_id, role)
    body = validate.body()
    validate.opt_string(body, "reason")
    enrollment = lookup.enrollment(enrollment_id)

    if role == config.ROLE_JURISDICTION_OFFICIAL and enrollment["jurisdiction_id"] != user_id:
        raise ApiError("ERR_JURISDICTION_MISMATCH")

    if enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_ENROLLMENT_STATE_INVALID")

    session = db.training_sessions.get(enrollment["training_session_id"])
    if session is None or session["status"] not in ("SCHEDULED", "ENROLLMENT_OPEN",
                                                    "ENROLLMENT_CLOSED"):
        raise ApiError("ERR_SESSION_STATE_INVALID")

    enrollment["status"] = "CANCELLED"
    db.touch(enrollment)
    db.touch(session)
    return response.object_response(serialize.training_enrollment(enrollment))


# ------------------------------------------------------------------ attendance
@bp.post("/training-sessions/<training_session_id>/attendance")
def record_attendance(training_session_id):
    middleware.require((config.ROLE_COUNCIL_ADMIN,))
    body = validate.body()
    raw_records = validate.req_list(body, "records")
    entries = []
    for entry in raw_records:
        if not isinstance(entry, dict):
            raise validate.bad_request("each records entry must be an object.")
        enrollment_id = validate.req_string(entry, "enrollment_id")
        outcome = validate.req_enum(entry, "outcome", ("ATTENDED", "NO_SHOW"))
        entries.append((enrollment_id, outcome))

    session = lookup.training_session(training_session_id)

    resolved = []
    for enrollment_id, outcome in entries:
        resolved.append((lookup.enrollment(enrollment_id), outcome))

    if session["status"] != "ENROLLMENT_CLOSED":
        raise ApiError("ERR_SESSION_STATE_INVALID")

    for enrollment, _ in resolved:
        if enrollment["training_session_id"] != session["id"]:
            raise ApiError("ERR_ENROLLMENT_SESSION_MISMATCH")

    for enrollment, _ in resolved:
        if enrollment["status"] != "ENROLLED":
            raise ApiError("ERR_ENROLLMENT_STATE_INVALID")

    if clock.now() < session["ends_at"]:
        raise ApiError("ERR_SESSION_NOT_FINISHED")

    listed = {}
    for enrollment, outcome in resolved:
        listed[enrollment["id"]] = outcome

    touched_jurisdictions = set()
    for enrollment, outcome in resolved:
        enrollment["status"] = outcome
        db.touch(enrollment)
        touched_jurisdictions.add(enrollment["jurisdiction_id"])

    for enrollment in db.ordered(derive.enrollments_of_session(session["id"])):
        if enrollment["id"] in listed:
            continue
        if enrollment["status"] == "ENROLLED":
            enrollment["status"] = "NO_SHOW"
            db.touch(enrollment)
            touched_jurisdictions.add(enrollment["jurisdiction_id"])

    session["status"] = "DELIVERED"
    db.touch(session)

    for jurisdiction_id in sorted(touched_jurisdictions):
        jurisdiction = db.jurisdictions.get(jurisdiction_id)
        if jurisdiction is not None:
            db.touch(jurisdiction)

    return response.object_response(serialize.training_session(session))
