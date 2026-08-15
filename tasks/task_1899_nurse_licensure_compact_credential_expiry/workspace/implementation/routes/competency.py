from flask import Blueprint, request

import db
from errors import (
    ERR_BOOKING_DUPLICATE,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_BOOKING_STATE,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_NURSE_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_REQUIREMENT_NOT_APPLICABLE,
    ERR_REQUIREMENT_NOT_FOUND,
    ERR_SESSION_FULL,
    ERR_SESSION_NOT_ENDED,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from services.derived import (
    compute_completion_expiry,
    recompute_posture,
    supersede_prior_completions,
)
from util import parse_time_loose

bp = Blueprint("competency", __name__)

EMPLOYMENT_TYPES = ["STAFF", "TRAVEL", "PER_DIEM"]

REQUIREMENT_SCHEMA = {
    "code": ("string", True, None),
    "name": ("string", True, None),
    "validity_months": ("int", True, None),
    "window_mode": ("string", True, ["ROLLING", "FISCAL"]),
    "mandatory": ("bool", True, None),
    "applies_to": ("array_enum", True, EMPLOYMENT_TYPES),
}

COMPLETION_SCHEMA = {
    "nurse_id": ("string", True, None),
    "requirement_id": ("string", True, None),
    "completed_on": ("date", True, None),
}

SESSION_SCHEMA = {
    "requirement_id": ("string", True, None),
    "title": ("string", True, None),
    "starts_at": ("datetime", True, None),
    "ends_at": ("datetime", True, None),
    "capacity": ("int", True, None),
}

BOOKING_SCHEMA = {
    "nurse_id": ("string", True, None),
}


# --- Competency requirements -----------------------------------------------------

@bp.route("/credentialing/competency-requirements", methods=["POST"])
def create_requirement():
    user_id, role = auth_context()
    require_role(role, {"ComplianceOfficer"})
    body = validate_body(get_body(), REQUIREMENT_SCHEMA)
    if any(r["code"] == body["code"] for r in all_entities("requirements")):
        raise ApiError(ERR_DUPLICATE_RESOURCE, "A requirement with this code already exists", 409)
    req = create_entity("requirements", {
        "code": body["code"],
        "name": body["name"],
        "validity_months": body["validity_months"],
        "window_mode": body["window_mode"],
        "mandatory": body["mandatory"],
        "applies_to": body["applies_to"],
    })
    return success_object(serialize("requirements", req), 201)


@bp.route("/credentialing/competency-requirements", methods=["GET"])
def list_requirements():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("requirements")
    value = request.args.get("window_mode")
    if value is not None:
        rows = [r for r in rows if r["window_mode"] == value]
    total = len(rows)
    return success_list([serialize("requirements", r) for r in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/competency-requirements/<reqId>", methods=["GET"])
def get_requirement(reqId):
    auth_context()
    req = get_or_404("requirements", reqId, ERR_NOT_FOUND, "Requirement not found")
    return success_object(serialize("requirements", req))


# --- Competency completions --------------------------------------------------------

@bp.route("/credentialing/competency-completions", methods=["POST"])
def create_completion():
    user_id, role = auth_context()
    require_role(role, {"Nurse", "CredentialingSpecialist"})
    body = validate_body(get_body(), COMPLETION_SCHEMA)
    if role == "Nurse" and body["nurse_id"] != user_id:
        raise ApiError(ERR_OWNERSHIP_VIOLATION, "Nurses may record only their own completions", 403)
    nurse = get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    req = get_or_404("requirements", body["requirement_id"], ERR_REQUIREMENT_NOT_FOUND, "requirement_id does not reference an existing requirement")
    if nurse["employment_type"] not in req["applies_to"]:
        raise ApiError(ERR_REQUIREMENT_NOT_APPLICABLE, "Requirement does not apply to this nurse's employment type", 422)
    completed_on = body["completed_on"]
    if completed_on > db.current_date():
        raise ApiError(ERR_INVALID_DATE_RANGE, "completed_on must not lie in the future", 422)
    expires_on = compute_completion_expiry(req, completed_on)
    completion = create_entity("completions", {
        "nurse_id": nurse["id"],
        "requirement_id": req["id"],
        "completed_on": completed_on.isoformat(),
        "expires_on": expires_on.isoformat(),
        "status": "CURRENT",
        "source": "MANUAL",
        "session_booking_id": None,
    })
    supersede_prior_completions(nurse["id"], req["id"], exclude_id=completion["id"])
    recompute_posture(nurse)
    return success_object(serialize("completions", completion), 201)


@bp.route("/credentialing/competency-completions", methods=["GET"])
def list_completions():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("completions")
    for param in ("nurse_id", "requirement_id", "session_booking_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [c for c in rows if c[param] == value]
    total = len(rows)
    return success_list([serialize("completions", c) for c in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/competency-completions/<completionId>", methods=["GET"])
def get_completion(completionId):
    auth_context()
    completion = get_or_404("completions", completionId, ERR_NOT_FOUND, "Completion not found")
    return success_object(serialize("completions", completion))


# --- Competency sessions & bookings -------------------------------------------------

@bp.route("/credentialing/competency-sessions", methods=["POST"])
def create_session():
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    body = validate_body(get_body(), SESSION_SCHEMA)
    req = get_or_404("requirements", body["requirement_id"], ERR_REQUIREMENT_NOT_FOUND, "requirement_id does not reference an existing requirement")
    if body["ends_at"] <= body["starts_at"]:
        raise ApiError(ERR_INVALID_DATE_RANGE, "ends_at must be strictly after starts_at", 422)
    session = create_entity("sessions", {
        "requirement_id": req["id"],
        "title": body["title"],
        "starts_at": body["starts_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ends_at": body["ends_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "capacity": body["capacity"],
        "booked_count": 0,
    })
    return success_object(serialize("sessions", session), 201)


@bp.route("/credentialing/competency-sessions", methods=["GET"])
def list_sessions():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("sessions")
    value = request.args.get("requirement_id")
    if value is not None:
        rows = [s for s in rows if s["requirement_id"] == value]
    total = len(rows)
    return success_list([serialize("sessions", s) for s in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/competency-sessions/<sessionId>", methods=["GET"])
def get_session(sessionId):
    auth_context()
    session = get_or_404("sessions", sessionId, ERR_NOT_FOUND, "Session not found")
    return success_object(serialize("sessions", session))


@bp.route("/credentialing/competency-sessions/<sessionId>/bookings", methods=["POST"])
def create_booking(sessionId):
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    session = get_or_404("sessions", sessionId, ERR_NOT_FOUND, "Session not found")
    body = validate_body(get_body(), BOOKING_SCHEMA)
    nurse = get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    if session["booked_count"] >= session["capacity"]:
        raise ApiError(ERR_SESSION_FULL, "Session has reached capacity", 409)
    if any(b for b in all_entities("bookings")
           if b["session_id"] == session["id"] and b["nurse_id"] == nurse["id"]):
        raise ApiError(ERR_BOOKING_DUPLICATE, "Nurse already has a booking in this session", 409)
    booking = create_entity("bookings", {
        "session_id": session["id"],
        "nurse_id": nurse["id"],
        "attended": False,
        "completion_id": None,
    })
    session["booked_count"] += 1
    touch(session)
    return success_object(serialize("bookings", booking), 201)


@bp.route("/credentialing/session-bookings", methods=["GET"])
def list_bookings():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("bookings")
    for param in ("session_id", "nurse_id", "completion_id"):
        value = request.args.get(param)
        if value is not None:
            rows = [b for b in rows if b[param] == value]
    total = len(rows)
    return success_list([serialize("bookings", b) for b in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/session-bookings/<bookingId>", methods=["GET"])
def get_booking(bookingId):
    auth_context()
    booking = get_or_404("bookings", bookingId, ERR_NOT_FOUND, "Booking not found")
    return success_object(serialize("bookings", booking))


@bp.route("/credentialing/session-bookings/<bookingId>/complete", methods=["POST"])
def complete_booking(bookingId):
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    booking = get_or_404("bookings", bookingId, ERR_NOT_FOUND, "Booking not found")
    if booking["attended"]:
        raise ApiError(ERR_INVALID_BOOKING_STATE, "Booking is already marked attended", 409)
    session = db.STORES["sessions"].get(booking["session_id"])
    if session is not None and db.logical_now() < parse_time_loose(session["ends_at"]):
        raise ApiError(ERR_SESSION_NOT_ENDED, "Session has not ended yet", 422)
    booking["attended"] = True
    nurse = db.STORES["nurses"].get(booking["nurse_id"])
    completion = None
    if session is not None and nurse is not None:
        req = db.STORES["requirements"].get(session["requirement_id"])
        completed_on = parse_time_loose(session["starts_at"]).date()
        expires_on = compute_completion_expiry(req, completed_on) if req else completed_on
        completion = create_entity("completions", {
            "nurse_id": nurse["id"],
            "requirement_id": session["requirement_id"],
            "completed_on": completed_on.isoformat(),
            "expires_on": expires_on.isoformat(),
            "status": "CURRENT",
            "source": "SESSION",
            "session_booking_id": booking["id"],
        })
        booking["completion_id"] = completion["id"]
        supersede_prior_completions(nurse["id"], session["requirement_id"], exclude_id=completion["id"])
        recompute_posture(nurse)
    touch(booking)
    return success_object(serialize("bookings", booking))


@bp.route("/credentialing/session-bookings/<bookingId>", methods=["DELETE"])
def delete_booking(bookingId):
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    booking = get_or_404("bookings", bookingId, ERR_NOT_FOUND, "Booking not found")
    if booking["attended"]:
        raise ApiError(ERR_INVALID_BOOKING_STATE, "An attended booking cannot be deleted", 409)
    session = db.STORES["sessions"].get(booking["session_id"])
    if session is not None:
        session["booked_count"] -= 1
        touch(session)
    del db.STORES["bookings"][booking["id"]]
    return "", 204
