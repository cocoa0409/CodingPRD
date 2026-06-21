"""Appointment endpoints (PRD §3.2) and its state machine."""
from flask import Blueprint, request

import serialize
from db import store, new_common, touch
from errors import err, ERR_INVALID_STATE, ERR_LICENSE_NOT_ACTIVE
from middleware import auth, get_json_body, lookup, check_version, paginate
from response import object_response, array_response
from services import derived
from util import require_str, validate_state_code

bp = Blueprint("appointments", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}


@bp.post("/appointments")
def create_appointment():
    auth({"AgencyAdmin"})
    body = get_json_body()
    carrier_id = require_str(body, "carrier_id")
    producer_id = require_str(body, "producer_id")
    with store.lock:
        lookup(store.carriers, carrier_id)
        lookup(store.producers, producer_id)
        state_code = validate_state_code(body.get("state_code"))
        rec = new_common()
        from clock import now_iso_clock
        rec.update(
            carrier_id=carrier_id,
            producer_id=producer_id,
            state_code=state_code,
            status="REQUESTED",
            requested_at=now_iso_clock(),
        )
        store.appointments[rec["id"]] = rec
        return object_response(serialize.appointment(rec), 201)


@bp.get("/appointments/<aid>")
def get_appointment(aid):
    auth(ALL_ROLES)
    rec = lookup(store.appointments, aid)
    return object_response(serialize.appointment(rec))


@bp.get("/appointments")
def list_appointments():
    auth(ALL_ROLES)
    carrier_id = request.args.get("carrier_id")
    producer_id = request.args.get("producer_id")
    state_code = request.args.get("state_code")
    status = request.args.get("status")
    recs = [
        a
        for a in store.appointments.values()
        if (carrier_id is None or a["carrier_id"] == carrier_id)
        and (producer_id is None or a["producer_id"] == producer_id)
        and (state_code is None or a["state_code"] == state_code)
        and (status is None or a["status"] == status)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.appointment(a) for a in page], limit, offset, total)


@bp.post("/appointments/<aid>/approve")
def approve_appointment(aid):
    auth({"AgencyAdmin"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.appointments, aid)
        if rec["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "only a REQUESTED appointment may be approved")
        check_version(rec, body.get("expected_appointment_version"), "expected_appointment_version")
        carrier = store.carriers[rec["carrier_id"]]
        producer = store.producers[rec["producer_id"]]
        if carrier["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "carrier must be ACTIVE to approve appointment")
        if producer["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "producer must be ACTIVE to approve appointment")
        rec["status"] = "APPROVED"
        touch(rec)
        return object_response(serialize.appointment(rec))


@bp.post("/appointments/<aid>/activate")
def activate_appointment(aid):
    auth({"AgencyAdmin"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.appointments, aid)
        if rec["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "only an APPROVED appointment may be activated")
        check_version(rec, body.get("expected_appointment_version"), "expected_appointment_version")
        # business: producer holds an ACTIVE license for the appointment's state.
        if not derived.has_active_license(rec["producer_id"], rec["state_code"]):
            raise err(ERR_LICENSE_NOT_ACTIVE, "producer has no ACTIVE license in this state")
        rec["status"] = "ACTIVE"
        touch(rec)
        return object_response(serialize.appointment(rec))


@bp.post("/appointments/<aid>/terminate")
def terminate_appointment(aid):
    auth({"AgencyAdmin"})
    body = get_json_body()
    with store.lock:
        rec = lookup(store.appointments, aid)
        if rec["status"] not in ("REQUESTED", "APPROVED", "ACTIVE"):
            raise err(ERR_INVALID_STATE, "appointment cannot be terminated from its current state")
        check_version(rec, body.get("expected_appointment_version"), "expected_appointment_version")
        rec["status"] = "TERMINATED"
        touch(rec)
        return object_response(serialize.appointment(rec))
