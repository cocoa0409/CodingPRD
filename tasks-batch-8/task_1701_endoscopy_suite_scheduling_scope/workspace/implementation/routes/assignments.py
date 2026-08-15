"""AnesthesiaAssignment endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND,
    ERR_BOOKING_NOT_FOUND,
    ERR_ANESTHESIA_PROVIDER_NOT_FOUND,
    ERR_ANESTHESIA_PROVIDER_SUSPENDED,
    ERR_ANESTHESIA_TYPE_NONE,
    ERR_ANESTHESIA_TIME_CONFLICT,
    ERR_ANESTHESIA_OWNERSHIP_MISMATCH,
    ERR_ASSIGNMENT_STATE_INVALID,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from validate import get_body, opt_nullable_str, req_str, require_path_resource, resolve_ref

bp = Blueprint("anesthesia_assignments", __name__)


@bp.post("/endoscopy/anesthesia-assignments")
def create_assignment():
    authorized(["SchedulingCoordinator"])
    body = get_body()
    # Rung 3 (existence), declared FK order: booking_id, anesthesia_provider_id
    booking = resolve_ref("bookings", body.get("booking_id"), ERR_BOOKING_NOT_FOUND)
    provider = resolve_ref("anesthesia_providers", body.get("anesthesia_provider_id"),
                           ERR_ANESTHESIA_PROVIDER_NOT_FOUND)
    # Rung 4 (schema)
    req_str(body, "booking_id")
    req_str(body, "anesthesia_provider_id")
    # Rung 8 (compliance): the anesthesia provider must be ACTIVE.
    if provider["credential_status"] != "ACTIVE":
        raise_error(ERR_ANESTHESIA_PROVIDER_SUSPENDED,
                    "anesthesia provider credential_status is SUSPENDED")
    # Rung 10 (constraint): nothing to staff when anesthesia_type is NONE.
    if booking["anesthesia_type"] == "NONE":
        raise_error(ERR_ANESTHESIA_TYPE_NONE,
                    "assignment creation requires anesthesia_type != NONE")
    # Closed-interval overlap on the booking's scheduled procedure window:
    # assignments whose windows merely touch at an endpoint conflict.
    new_start, new_end = booking["scheduled_start"], booking["scheduled_end"]
    for other in db["anesthesia_assignments"].values():
        if other["anesthesia_provider_id"] != provider["id"]:
            continue
        if other["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        other_booking = db["bookings"].get(other["booking_id"])
        if other_booking is None:
            continue
        o_start, o_end = other_booking["scheduled_start"], other_booking["scheduled_end"]
        if new_start <= o_end and o_start <= new_end:
            raise_error(ERR_ANESTHESIA_TIME_CONFLICT,
                        "closed-interval overlap with an active assignment of this provider")
    rec = new_record("anesthesia_assignments", {
        "booking_id": booking["id"],
        "anesthesia_provider_id": provider["id"],
        # minutes is a creation-time snapshot of booking.procedure_minutes;
        # it is never recomputed.
        "minutes": booking["procedure_minutes"],
        "status": "ASSIGNED",
        "cancel_reason": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/anesthesia-assignments")
def list_assignments():
    return list_response("anesthesia_assignments", {
        "booking_id": request.args.get("booking_id"),
        "anesthesia_provider_id": request.args.get("anesthesia_provider_id"),
        "status": request.args.get("status"),
    })


@bp.get("/endoscopy/anesthesia-assignments/<rid>")
def get_assignment(rid):
    return get_one("anesthesia_assignments", rid, ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND)


@bp.post("/endoscopy/anesthesia-assignments/<rid>/confirm")
def confirm_assignment(rid):
    caller = authorized(["AnesthesiaProvider"])
    assignment = require_path_resource("anesthesia_assignments", rid,
                                       ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND)
    get_body()
    # Rung 6 (ownership): only the assigned anesthesia provider confirms.
    if caller.user_id != assignment["anesthesia_provider_id"]:
        raise_error(ERR_ANESTHESIA_OWNERSHIP_MISMATCH,
                    "X-User-ID must equal the assignment's anesthesia_provider_id")
    # Rung 7 (state)
    if assignment["status"] != "ASSIGNED":
        raise_error(ERR_ASSIGNMENT_STATE_INVALID,
                    "confirm requires status ASSIGNED")
    assignment["status"] = "CONFIRMED"
    touch(assignment)
    return success_object(public(assignment))


@bp.post("/endoscopy/anesthesia-assignments/<rid>/cancel")
def cancel_assignment(rid):
    authorized(["SchedulingCoordinator", "AnesthesiaProvider"])
    assignment = require_path_resource("anesthesia_assignments", rid,
                                       ERR_ANESTHESIA_ASSIGNMENT_NOT_FOUND)
    body = get_body()
    reason = opt_nullable_str(body, "reason", None)
    # Rung 7 (state)
    if assignment["status"] not in ("ASSIGNED", "CONFIRMED"):
        raise_error(ERR_ASSIGNMENT_STATE_INVALID,
                    "cancel requires status ASSIGNED or CONFIRMED")
    assignment["status"] = "CANCELLED"
    if reason is not None:
        assignment["cancel_reason"] = reason
    touch(assignment)
    return success_object(public(assignment))
