"""LiveEvent endpoints (PRD §3.6-§3.7): schedule, go-on-air, wrap, settle, cancel."""
from datetime import timedelta
from flask import Blueprint, request

import serialize
from auth import ALL_ROLES, body, guarded
from db import DB, now, stamp_new, touch
from errors import (
    ApiError,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_GO_ON_AIR_BLOCKED,
    invalid_transition,
    not_found,
)
from respond import list_response, ok_object
from services import workflow
from util import opt_int, req_dt, req_enum, req_str

bp = Blueprint("live_events", __name__)

CERTIFICATIONS = {"CERT_CBC", "CERT_CART"}


def get_event(event_id):
    e = DB.live_events.get(event_id)
    if e is None:
        raise not_found("Live event not found")
    return e


@bp.post("/caption-ad/live-events")
@guarded({"Scheduler"})
def create_live_event(_user_id, _role):
    data = body()
    client_id = data.get("client_id")
    if not isinstance(client_id, str) or client_id not in DB.clients:
        raise not_found("Referenced client_id does not exist")
    title = req_str(data, "title")
    channel_id = req_str(data, "channel_id")
    start_at = req_dt(data, "start_at")
    end_at = req_dt(data, "end_at")
    if end_at <= start_at:
        from errors import validation
        raise validation("Field 'end_at' must be after 'start_at'")
    required_certification = req_enum(data, "required_certification", CERTIFICATIONS)
    prep_minutes = opt_int(data, "prep_minutes", default=15, minimum=0)
    wrap_minutes = opt_int(data, "wrap_minutes", default=5, minimum=0)
    client = DB.clients[client_id]
    if client["client_status"] != "ACTIVE":
        raise ApiError(ERR_CLIENT_NOT_ACTIVE, 409, "Client is not ACTIVE")
    rec = {
        "client_id": client_id,
        "title": title,
        "channel_id": channel_id,
        "start_at": start_at,
        "end_at": end_at,
        "required_certification": required_certification,
        "prep_minutes": prep_minutes,
        "wrap_minutes": wrap_minutes,
        "event_status": "SCHEDULED",
    }
    stamp_new(rec)
    DB.live_events[rec["id"]] = rec
    return ok_object(serialize.live_event(rec), status=201)


@bp.get("/caption-ad/live-events")
@guarded(set(ALL_ROLES))
def list_live_events(_user_id, _role):
    records = list(DB.live_events.values())
    for param, field in (
        ("client_id", "client_id"),
        ("channel_id", "channel_id"),
        ("event_status", "event_status"),
    ):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[field] == v]
    return list_response(records, serialize.live_event)


@bp.get("/caption-ad/live-events/<liveEventId>")
@guarded(set(ALL_ROLES))
def get_one_live_event(liveEventId, _user_id, _role):
    return ok_object(serialize.live_event(get_event(liveEventId)))


@bp.post("/caption-ad/live-events/<liveEventId>/go-on-air")
@guarded({"Scheduler"})
def go_on_air(liveEventId, _user_id, _role):
    e = get_event(liveEventId)
    if e["event_status"] not in ("SCHEDULED", "BRIEFED"):
        raise invalid_transition("Only a SCHEDULED or BRIEFED event can go on air")
    t = now()
    # Admitted only from thirty minutes before start_at up to (but not
    # including) end_at.
    if not (e["start_at"] - timedelta(minutes=30) <= t < e["end_at"]):
        raise invalid_transition("go-on-air is admitted only within [start_at - 30min, end_at)")
    if not workflow.confirmed_assignment_exists(e["id"]):
        raise ApiError(ERR_GO_ON_AIR_BLOCKED, 409, "go-on-air requires a CONFIRMED assignment")
    e["event_status"] = "ON_AIR"
    touch(e)
    for a in DB.assignments.values():
        if a["live_event_id"] == e["id"] and a["assignment_status"] == "CONFIRMED":
            a["assignment_status"] = "LIVE"
            touch(a)
    return ok_object(serialize.live_event(e))


@bp.post("/caption-ad/live-events/<liveEventId>/wrap")
@guarded({"Scheduler"})
def wrap_event(liveEventId, _user_id, _role):
    e = get_event(liveEventId)
    if e["event_status"] != "ON_AIR":
        raise invalid_transition("Only an ON_AIR event can wrap")
    if now() < e["end_at"]:
        raise invalid_transition("The event cannot wrap before its end_at")
    e["event_status"] = "WRAP"
    touch(e)
    for a in DB.assignments.values():
        if a["live_event_id"] == e["id"] and a["assignment_status"] == "LIVE":
            a["assignment_status"] = "COMPLETED"
            touch(a)
    return ok_object(serialize.live_event(e))


@bp.post("/caption-ad/live-events/<liveEventId>/settle")
@guarded({"Scheduler"})
def settle_event(liveEventId, _user_id, _role):
    e = get_event(liveEventId)
    if e["event_status"] != "WRAP":
        raise invalid_transition("Only a WRAP event can settle")
    e["event_status"] = "SETTLED"
    touch(e)
    workflow.create_archive_item(live_event_id=e["id"])
    return ok_object(serialize.live_event(e))


@bp.post("/caption-ad/live-events/<liveEventId>/cancel")
@guarded({"Scheduler"})
def cancel_event(liveEventId, _user_id, _role):
    e = get_event(liveEventId)
    if e["event_status"] not in ("SCHEDULED", "BRIEFED"):
        raise invalid_transition("Only a SCHEDULED or BRIEFED event can be cancelled")
    e["event_status"] = "CANCELLED"
    touch(e)
    for a in DB.assignments.values():
        if a["live_event_id"] == e["id"] and a["assignment_status"] in ("OFFERED", "ACCEPTED", "CONFIRMED"):
            a["assignment_status"] = "CANCELLED"  # no make-up credit
            touch(a)
    return ok_object(serialize.live_event(e))
