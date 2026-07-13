"""Vehicles and transportation requests (buffered vehicle overlap, dual axes)."""
from datetime import timedelta

from flask import Blueprint, request

from store import db, base_common, touch
from core import (
    require_actor, authorize, check_ownership, get_body, ok_object, ok_array,
    paginate, req_str, req_int, err, req_datetime, parse_dt,
)
from lookups import get_vehicle, get_participant, get_session, get_transport
from serializers import ser_vehicle, ser_transport

bp = Blueprint("transport", __name__)

TURNAROUND = timedelta(minutes=15)


@bp.post("/vehicles")
def create_vehicle():
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    body = get_body()
    name = req_str(body, "name")
    seat_capacity = req_int(body, "seat_capacity", minimum=1)
    rec = base_common(with_version=False)
    rec.update({"name": name, "seat_capacity": seat_capacity})
    db.vehicles[rec["id"]] = rec
    return ok_object(ser_vehicle(rec), 201)


@bp.post("/transportation-requests")
def create_transport():
    actor = require_actor()
    authorize(actor, {"Participant", "Coordinator"})
    body = get_body()
    participant_id = req_str(body, "participant_id")
    vehicle_id = req_str(body, "vehicle_id")
    linked_session_id = req_str(body, "linked_session_id")
    starts_raw, starts = req_datetime(body, "starts_at")
    ends_raw, ends = req_datetime(body, "ends_at")
    check_ownership(actor, participant_id)

    participant = get_participant(participant_id)
    get_vehicle(vehicle_id)
    get_session(linked_session_id)

    if participant["status"] != "ACTIVE":
        raise err("ERR_PARTICIPANT_INACTIVE", "Participant is not ACTIVE")
    if not (starts < ends):
        raise err("ERR_INVALID_TIME_WINDOW", "starts_at must be before ends_at")
    # Buffered vehicle overlap: expand new window +/- 15-min turnaround.
    b_start = starts - TURNAROUND
    b_end = ends + TURNAROUND
    for t in db.transports.values():
        if t["vehicle_id"] != vehicle_id:
            continue
        e_start = parse_dt(t["starts_at"])
        e_end = parse_dt(t["ends_at"])
        if b_start < e_end and e_start < b_end:
            raise err("ERR_VEHICLE_UNAVAILABLE", "Vehicle unavailable in this window")

    rec = base_common()
    rec.update({
        "participant_id": participant_id,
        "vehicle_id": vehicle_id,
        "linked_session_id": linked_session_id,
        "starts_at": starts_raw,
        "ends_at": ends_raw,
        "eligibility_status": "PENDING",
        "trip_status": "SCHEDULED",
    })
    db.transports[rec["id"]] = rec
    return ok_object(ser_transport(rec), 201)


@bp.get("/transportation-requests/<tid>")
def get_transport_route(tid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    return ok_object(ser_transport(get_transport(tid)))


@bp.get("/transportation-requests")
def list_transports():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    rows = list(db.transports.values())
    args = request.args
    for key in ("participant_id", "vehicle_id", "linked_session_id"):
        if key in args:
            rows = [r for r in rows if r.get(key) == args.get(key)]
    window, page = paginate(rows)
    return ok_array([ser_transport(r) for r in window], page)


@bp.post("/transportation-requests/<tid>/approve")
def approve_transport(tid):
    actor = require_actor()
    authorize(actor, {"Coordinator"})
    rec = get_transport(tid)
    if rec["eligibility_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Eligibility is not PENDING")
    session = db.sessions.get(rec["linked_session_id"])
    if session is None or session["status"] != "SCHEDULED":
        raise err("ERR_SESSION_NOT_SCHEDULED", "Linked session is not SCHEDULED")
    rec["eligibility_status"] = "APPROVED"
    touch(rec)
    return ok_object(ser_transport(rec))


@bp.post("/transportation-requests/<tid>/complete")
def complete_transport(tid):
    actor = require_actor()
    authorize(actor, {"Coordinator"})
    rec = get_transport(tid)
    if rec["trip_status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Trip is not SCHEDULED")
    if rec["eligibility_status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Trip eligibility is not APPROVED")
    rec["trip_status"] = "COMPLETED"
    touch(rec)
    return ok_object(ser_transport(rec))
