"""Infusion appointments: booking, confirmation, cancellation (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint

from db import db, next_seq, touch
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_AUTH_NOT_APPROVED,
    ERR_OUTSIDE_VALIDITY_WINDOW,
    ERR_SITE_NOT_ALLOWED,
    ERR_CHAIR_SCHEDULE_CONFLICT,
    ERR_CLEARANCE_NOT_CLEARED,
)
from middleware import authorized
from response import success_object
from routes.helpers import (
    get_request, get_chair, get_appointment,
    list_response, latest_site_determination,
)
from serializers import serialize
from util import new_id, CLOCK
from validate import get_body, req_str, req_dt, check_window_order

bp = Blueprint("appointments", __name__)


def _check_within_validity_window(req, scheduled_start):
    """Closed interval: auth_valid_from <= scheduled_start <= auth_valid_to."""
    if (req["auth_valid_from"] is None or req["auth_valid_to"] is None
            or scheduled_start < req["auth_valid_from"]
            or scheduled_start > req["auth_valid_to"]):
        raise_error(ERR_OUTSIDE_VALIDITY_WINDOW,
                    "scheduled_start is outside the authorization validity window")


def _chair_conflict(chair, new_start, new_end):
    """Buffered half-open interval overlap: [start, end + buffer). Adjacency
    (new_start == existing buffered end) is permitted."""
    buffer = timedelta(minutes=int(chair["turnover_buffer_minutes"]))
    new_buffered_end = new_end + buffer
    for other in db["appointments"].values():
        if other["chair_id"] != chair["id"]:
            continue
        if other["status"] in ("CANCELLED", "MISSED"):
            continue
        other_buffered_end = other["scheduled_end"] + buffer
        if new_start < other_buffered_end and other["scheduled_start"] < new_buffered_end:
            return other
    return None


@bp.post("/infusion/authorization-requests/<rid>/appointments")
def book_appointment(rid):
    authorized(["Scheduler"])
    body = get_body()
    chair_id = req_str(body, "chair_id")
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    check_window_order(scheduled_start, scheduled_end)

    # existence left to right: request, then chair
    req = get_request(rid)
    chair = get_chair(chair_id)

    if req["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED,
                    f"booking requires an APPROVED request, found {req['status']}")
    _check_within_validity_window(req, scheduled_start)

    latest = latest_site_determination(req["id"])
    if latest is None or chair["site_type"] != latest["recommended_site_type"]:
        raise_error(ERR_SITE_NOT_ALLOWED,
                    "chair site_type does not match the latest determination's "
                    "recommended_site_type")

    if _chair_conflict(chair, scheduled_start, scheduled_end) is not None:
        raise_error(ERR_CHAIR_SCHEDULE_CONFLICT,
                    "the chair is already occupied in that buffered window")

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "authorization_request_id": req["id"],
        "chair_id": chair["id"],
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["appointments"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/authorization-requests/<rid>/appointments")
def list_request_appointments(rid):
    authorized(["Scheduler", "AuthCoordinator", "MedicalDirector"])
    get_request(rid)
    items = [a for a in db["appointments"].values() if a["authorization_request_id"] == rid]
    return list_response(items)


@bp.post("/infusion/appointments/<aid>/confirm")
def confirm_appointment(aid):
    authorized(["Scheduler"])
    get_body()
    appt = get_appointment(aid)
    if appt["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"appointment is {appt['status']}; only SCHEDULED may be confirmed")
    req = get_request(appt["authorization_request_id"])
    if req["status"] != "APPROVED":
        raise_error(ERR_AUTH_NOT_APPROVED,
                    f"confirmation requires the parent request APPROVED, found {req['status']}")
    # the request's unique clearance in ESTIMATED/CLEARED must be CLEARED
    # (an ON_HOLD clearance fails this gate)
    cleared = any(c["authorization_request_id"] == req["id"] and c["status"] == "CLEARED"
                  for c in db["financial_clearances"].values())
    if not cleared:
        raise_error(ERR_CLEARANCE_NOT_CLEARED,
                    "confirmation requires a CLEARED financial clearance")
    _check_within_validity_window(req, appt["scheduled_start"])

    appt["status"] = "CONFIRMED"
    touch(appt, CLOCK.now())
    return success_object(serialize(appt))


@bp.post("/infusion/appointments/<aid>/cancel")
def cancel_appointment(aid):
    authorized(["Scheduler"])
    get_body()
    appt = get_appointment(aid)
    if appt["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE,
                    f"appointment is {appt['status']}; only SCHEDULED or CONFIRMED may be cancelled")
    appt["status"] = "CANCELLED"
    touch(appt, CLOCK.now())
    return success_object(serialize(appt))
