"""Appointment endpoints (PRD §3.2). Overlap guards: preparer intervals are
half-open [start,end) (adjacency allowed); client intervals are closed [start,end]
(shared boundary collides). Transition preconditions read the logical clock."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from models import make_appointment, appointment_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_office, get_client, get_preparer,
                           get_appointment, paginate, page_slice)
from timeutil import parse_iso

bp = Blueprint("appointments", __name__)

TERMINAL_APPT = {"COMPLETED", "NO_SHOW", "CANCELLED"}

# Appointment transition table: from -> {to: actor allowed (any of these roles)}
APPT_TRANSITIONS = {
    ("SCHEDULED", "CHECKED_IN"),
    ("CHECKED_IN", "COMPLETED"),
    ("SCHEDULED", "NO_SHOW"),
    ("SCHEDULED", "CANCELLED"),
}


def _half_open_overlap(s1, e1, s2, e2):
    """True if [s1,e1) and [s2,e2) overlap (adjacency end==start allowed)."""
    return s1 < e2 and s2 < e1


def _closed_overlap(s1, e1, s2, e2):
    """True if [s1,e1] and [s2,e2] overlap including shared boundaries."""
    return s1 <= e2 and s2 <= e1


@bp.post("/offices/<office_id>/appointments")
def book_appointment(office_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager"})
    office = get_office(office_id)
    body = get_json_body()

    client_id = body.get("client_id")
    preparer_id = body.get("preparer_id")
    if not isinstance(client_id, str) or not client_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "client_id is required")
    if not isinstance(preparer_id, str) or not preparer_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "preparer_id is required")
    # body FK existence (404) before remaining well-formedness
    get_client(client_id)
    get_preparer(preparer_id)

    start_raw = body.get("start_utc")
    end_raw = body.get("end_utc")
    if not isinstance(start_raw, str) or not start_raw:
        raise errors.err(errors.ERR_INVALID_REQUEST, "start_utc is required")
    if not isinstance(end_raw, str) or not end_raw:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_utc is required")
    try:
        start_dt = parse_iso(start_raw)
        end_dt = parse_iso(end_raw)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "start_utc/end_utc must be valid instants")
    if not (end_dt > start_dt):
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_utc must be strictly after start_utc")

    # Overlap guards (priority 10 preparer, then 11 client per SCAFFOLD).
    for appt in db.appointments.values():
        if appt["status"] in TERMINAL_APPT:
            continue
        if appt["preparer_id"] == preparer_id:
            a_s = parse_iso(appt["start_utc"])
            a_e = parse_iso(appt["end_utc"])
            if _half_open_overlap(start_dt, end_dt, a_s, a_e):
                raise errors.err(errors.ERR_PREPARER_DOUBLE_BOOKED,
                                 "Preparer already booked for an overlapping interval")
    for appt in db.appointments.values():
        if appt["status"] in TERMINAL_APPT:
            continue
        if appt["client_id"] == client_id:
            a_s = parse_iso(appt["start_utc"])
            a_e = parse_iso(appt["end_utc"])
            if _closed_overlap(start_dt, end_dt, a_s, a_e):
                raise errors.err(errors.ERR_CLIENT_DOUBLE_BOOKED,
                                 "Client already booked for an overlapping interval")

    appt = make_appointment(office_id, client_id, preparer_id, start_raw, end_raw)
    return object_response(appointment_dict(appt), 201)


@bp.get("/offices/<office_id>/appointments")
def list_office_appointments(office_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    get_office(office_id)
    limit, offset = paginate()

    items = [a for a in db.appointments.values() if a["office_id"] == office_id]
    page, total = page_slice(items, limit, offset)
    return array_response([appointment_dict(a) for a in page], limit, offset, total, 200)


@bp.get("/appointments")
def list_appointments():
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    limit, offset = paginate()

    office_id = request.args.get("office_id")
    client_id = request.args.get("client_id")
    preparer_id = request.args.get("preparer_id")
    items = list(db.appointments.values())
    if office_id is not None:
        items = [a for a in items if a["office_id"] == office_id]
    if client_id is not None:
        items = [a for a in items if a["client_id"] == client_id]
    if preparer_id is not None:
        items = [a for a in items if a["preparer_id"] == preparer_id]

    page, total = page_slice(items, limit, offset)
    return array_response([appointment_dict(a) for a in page], limit, offset, total, 200)


@bp.get("/appointments/<appointment_id>")
def get_appointment_ep(appointment_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    appt = get_appointment(appointment_id)
    return object_response(appointment_dict(appt), 200)


@bp.post("/appointments/<appointment_id>/transition")
def transition_appointment(appointment_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager"})
    appt = get_appointment(appointment_id)
    body = get_json_body()

    to = body.get("to")
    if to not in ("CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "to must be a valid appointment state")

    current = appt["status"]
    if (current, to) not in APPT_TRANSITIONS:
        raise errors.err(errors.ERR_INVALID_STATE,
                         "Transition %s -> %s is not defined" % (current, to))

    clock = db.clock
    if to == "CHECKED_IN":
        start_dt = parse_iso(appt["start_utc"])
        if clock < start_dt:
            raise errors.err(errors.ERR_APPOINTMENT_WINDOW_NOT_OPEN,
                             "Cannot check in before the appointment window opens")
    elif to == "NO_SHOW":
        end_dt = parse_iso(appt["end_utc"])
        if clock < end_dt:
            raise errors.err(errors.ERR_APPOINTMENT_WINDOW_NOT_OPEN,
                             "Cannot record a no-show before the window is fully past")

    appt["status"] = to
    touch(appt)
    return object_response(appointment_dict(appt), 200)
