"""Activity offerings and enrollments. PRD §3.8."""
from flask import Blueprint, request

import db
import errors
import response
from errors import ApiError
from middleware import get_identity, require_role, get_json_body, parse_pagination
from services import validate, serialize, calc
from services.store import base_fields, require, touch, paginate, guardian_owns_camper

bp = Blueprint("activities", __name__)


@bp.route("/sessions/<sid>/activities", methods=["POST"])
def create_offering(sid):
    _uid, role = get_identity()
    require_role(role, {"CampDirector"})
    session = require(db.sessions, sid)
    body = get_json_body()

    name = validate.require_str(body, "name")
    slot_day = validate.require_int(body, "slot_day")
    if slot_day < 1:
        raise validate.bad_request("slot_day must be a 1-based positive integer.")
    starts_minute = validate.require_int(body, "starts_minute")
    ends_minute = validate.require_int(body, "ends_minute")
    if starts_minute < 0 or starts_minute >= 1440:
        raise validate.bad_request("starts_minute must be in [0, 1440).")
    if ends_minute <= starts_minute:
        raise validate.bad_request("ends_minute must be > starts_minute.")
    seat_capacity = validate.require_int(body, "seat_capacity")
    if seat_capacity < 0:
        raise validate.bad_request("seat_capacity must be non-negative.")
    buffer_minutes = validate.optional_int(body, "setup_buffer_minutes", 0)
    if buffer_minutes < 0:
        raise validate.bad_request("setup_buffer_minutes must be non-negative.")
    requires_swim = validate.optional_bool(body, "requires_swim_test", False)

    o = base_fields()
    o.update({
        "session_id": session["id"],
        "name": name,
        "slot_day": slot_day,
        "starts_minute": starts_minute,
        "ends_minute": ends_minute,
        "setup_buffer_minutes": buffer_minutes,
        "seat_capacity": seat_capacity,
        "requires_swim_test": requires_swim,
        "seats_taken": 0,
    })
    db.activity_offerings[o["id"]] = o
    return response.success(serialize.activity_offering(o), 201)


@bp.route("/sessions/<sid>/activities", methods=["GET"])
def list_offerings(sid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    require(db.sessions, sid)
    limit, offset = parse_pagination()

    session_id_f = request.args.get("session_id")
    slot_day_f = request.args.get("slot_day")

    items = [o for o in db.activity_offerings.values() if o["session_id"] == sid]
    if session_id_f is not None:
        items = [o for o in items if o["session_id"] == session_id_f]
    if slot_day_f is not None:
        try:
            day = int(slot_day_f)
        except (ValueError, TypeError):
            raise validate.bad_request("slot_day filter must be an integer.")
        items = [o for o in items if o["slot_day"] == day]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.activity_offering(o) for o in page], limit, offset, total)


@bp.route("/activities/<oid>", methods=["GET"])
def get_offering(oid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector", "InfirmaryNurse"})
    o = require(db.activity_offerings, oid)
    return response.success(serialize.activity_offering(o), 200)


@bp.route("/activity-enrollments", methods=["POST"])
def book_enrollment():
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    body = get_json_body()

    if "offering_id" not in body or not isinstance(body.get("offering_id"), str):
        raise validate.bad_request("offering_id is required.")
    if "application_id" not in body or not isinstance(body.get("application_id"), str):
        raise validate.bad_request("application_id is required.")

    offering = db.activity_offerings.get(body["offering_id"])
    if offering is None:
        raise ApiError(errors.ERR_REFERENTIAL_MISMATCH, 409, "Offering does not resolve.")
    application = db.applications.get(body["application_id"])
    if application is None:
        raise ApiError(errors.ERR_REFERENTIAL_MISMATCH, 409, "Application does not resolve.")

    camper = db.campers.get(application["camper_id"])
    if camper is not None:
        guardian_owns_camper(uid, role, camper)

    # Referential scope: offering's session must match the application's session.
    if offering["session_id"] != application["session_id"]:
        raise ApiError(errors.ERR_REFERENTIAL_MISMATCH, 409,
                       "Offering does not belong to the application's session.")

    # Swim-test waterfront gate (p7).
    if offering["requires_swim_test"] and camper["health_status"] != "CLEARED":
        raise ApiError(errors.ERR_SWIM_TEST_REQUIRED, 422, "Swim test (CLEARED) required for this offering.")

    # Time/buffer conflicts against existing BOOKED enrollments on the same
    # slot_day (ERR_ACTIVITY_TIME_CONFLICT, p9).
    for e in db.activity_enrollments.values():
        if e["application_id"] != application["id"] or e["status"] != "BOOKED":
            continue
        existing_offering = db.activity_offerings.get(e["offering_id"])
        if existing_offering is None:
            continue
        if existing_offering["slot_day"] != offering["slot_day"]:
            continue
        if calc.activity_conflicts(offering, existing_offering):
            raise ApiError(errors.ERR_ACTIVITY_TIME_CONFLICT, 422, "Activity time/buffer conflict.")

    # Seat capacity (p10).
    if offering["seats_taken"] + 1 > offering["seat_capacity"]:
        raise ApiError(errors.ERR_ACTIVITY_FULL, 409, "Offering is full.")

    e = base_fields()
    e.update({
        "offering_id": offering["id"],
        "application_id": application["id"],
        "status": "BOOKED",
    })
    db.activity_enrollments[e["id"]] = e
    offering["seats_taken"] += 1
    touch(offering)

    return response.success(serialize.activity_enrollment(e), 201)


@bp.route("/activity-enrollments", methods=["GET"])
def list_enrollments():
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    limit, offset = parse_pagination()

    offering_f = request.args.get("offering_id")
    app_f = request.args.get("application_id")
    status_f = request.args.get("status")

    items = list(db.activity_enrollments.values())
    if role == "Guardian":
        owned_campers = {c["id"] for c in db.campers.values() if c["guardian_user_id"] == uid}
        owned_apps = {a["id"] for a in db.applications.values() if a["camper_id"] in owned_campers}
        items = [e for e in items if e["application_id"] in owned_apps]
    if offering_f is not None:
        items = [e for e in items if e["offering_id"] == offering_f]
    if app_f is not None:
        items = [e for e in items if e["application_id"] == app_f]
    if status_f is not None:
        items = [e for e in items if e["status"] == status_f]

    page, total = paginate(items, limit, offset)
    return response.success_list([serialize.activity_enrollment(e) for e in page], limit, offset, total)


@bp.route("/activity-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    e = require(db.activity_enrollments, eid)
    if role == "Guardian":
        application = db.applications.get(e["application_id"])
        if application is not None:
            camper = db.campers.get(application["camper_id"])
            if camper is not None:
                guardian_owns_camper(uid, role, camper)
    return response.success(serialize.activity_enrollment(e), 200)


@bp.route("/activity-enrollments/<eid>/drop", methods=["POST"])
def drop_enrollment(eid):
    uid, role = get_identity()
    require_role(role, {"Guardian"})
    e = require(db.activity_enrollments, eid)

    application = db.applications.get(e["application_id"])
    if application is not None:
        camper = db.campers.get(application["camper_id"])
        if camper is not None:
            guardian_owns_camper(uid, role, camper)

    if e["status"] != "BOOKED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Enrollment is not BOOKED.")

    e["status"] = "DROPPED"
    touch(e)
    offering = db.activity_offerings.get(e["offering_id"])
    if offering is not None:
        offering["seats_taken"] = max(0, offering["seats_taken"] - 1)
        touch(offering)

    return response.success(serialize.activity_enrollment(e), 200)
