"""ServiceEvent endpoints: lifecycle spine, reschedule (OCC), waiver bump, rebook."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_EVENT_NOT_FOUND,
    ERR_INVALID_EVENT_TRANSITION,
    ERR_EVENT_NOT_READY,
    ERR_UNRESOLVED_SPONSORSHIPS,
    ERR_EVENT_IN_PAST,
    ERR_STALE_EVENT_VERSION,
    ERR_REBOOK_NOT_ELIGIBLE,
    ERR_VALIDATION,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.cascades import (
    event_complete_cascade,
    event_cancel_cascade,
    waiver_version_bump_cascade,
)
from services.core import mint, bump, ser_event, sort_entities
from timeutil import parse_datetime
from validate import req_string, req_int, opt_int, req_present, check_range

bp = Blueprint("events", __name__)

CEM = ["CommunityEngagementManager"]
EVENT_LEAD_TIME = timedelta(hours=24)


def load_event(event_id):
    ev = db.events.get(event_id)
    if ev is None:
        raise_err(ERR_EVENT_NOT_FOUND, "service event not found")
    return ev


def _parse_window(data):
    start_raw = req_present(data, "event_start_at")
    end_raw = req_present(data, "event_end_at")
    start = parse_datetime(start_raw, "event_start_at")
    end = parse_datetime(end_raw, "event_end_at")
    return start_raw, end_raw, start, end


def _check_window(start, end):
    """Temporal gate: start >= now + 24h and end strictly after start (ERR_EVENT_IN_PAST)."""
    if start < db.now() + EVENT_LEAD_TIME:
        raise_err(ERR_EVENT_IN_PAST, "event_start_at must be at least 24h after the current clock")
    if end <= start:
        raise_err(ERR_EVENT_IN_PAST, "event_end_at must be strictly after event_start_at")


@bp.post("/service-events")
def create_event():
    authenticate(CEM)
    data = body()
    name = req_string(data, "name")
    start_raw, end_raw, start, end = _parse_window(data)
    budget = req_int(data, "budget_cents")
    waiver_version = opt_int(data, "waiver_document_version", 1)
    # pipeline step 9 (temporal) precedes step 11 (range validation)
    _check_window(start, end)
    check_range(budget >= 0, "budget_cents must be >= 0")
    check_range(waiver_version >= 1, "waiver_document_version must be >= 1")
    ev = mint()
    ev.update(
        {
            "name": name,
            "event_start_at": start_raw,
            "event_end_at": end_raw,
            "_start": start,
            "_end": end,
            "status": "PLANNING",
            "budget_cents": budget,
            "waiver_document_version": waiver_version,
            "source_event_id": None,
            "repeat_booking_bonus": False,
        }
    )
    db.events[ev["id"]] = ev
    return success_object(ser_event(ev), 201)


@bp.get("/service-events")
def list_events():
    authenticate(["Any"])
    items = list(db.events.values())
    status = request.args.get("status")
    source_event_id = request.args.get("source_event_id")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if source_event_id is not None:
        items = [e for e in items if e["source_event_id"] == source_event_id]
    return success_list([ser_event(e) for e in sort_entities(items)])


@bp.get("/service-events/<eventId>")
def get_event(eventId):
    authenticate(["Any"])
    return success_object(ser_event(load_event(eventId)))


def _transition(event_id, allowed_from, error_msg):
    ev = load_event(event_id)
    if ev["status"] not in allowed_from:
        raise_err(ERR_INVALID_EVENT_TRANSITION, error_msg)
    return ev


@bp.post("/service-events/<eventId>/open-registration")
def open_registration(eventId):
    authenticate(CEM)
    ev = _transition(eventId, ("PLANNING",), "event must be PLANNING to open registration")
    ev["status"] = "REGISTRATION_OPEN"
    bump(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/lock-registration")
def lock_registration(eventId):
    authenticate(CEM)
    ev = _transition(
        eventId, ("REGISTRATION_OPEN",), "event must be REGISTRATION_OPEN to lock registration"
    )
    ev["status"] = "REGISTRATION_LOCKED"
    bump(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/begin")
def begin_event(eventId):
    authenticate(CEM)
    ev = _transition(eventId, ("REGISTRATION_LOCKED",), "event must be REGISTRATION_LOCKED to begin")
    if calc.event_posture(ev) != "READY":
        raise_err(ERR_EVENT_NOT_READY, "readiness_posture must be READY to begin")
    ev["status"] = "IN_PROGRESS"
    bump(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/complete")
def complete_event(eventId):
    authenticate(CEM)
    ev = _transition(eventId, ("IN_PROGRESS",), "event must be IN_PROGRESS to complete")
    event_complete_cascade(ev)
    ev["status"] = "COMPLETED"
    bump(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/close")
def close_event(eventId):
    authenticate(CEM)
    ev = _transition(eventId, ("COMPLETED",), "event must be COMPLETED to close")
    unresolved = any(
        sp["event_id"] == ev["id"] and sp["status"] in ("PLEDGED", "COMMITTED")
        for sp in db.sponsorships.values()
    )
    if unresolved:
        raise_err(ERR_UNRESOLVED_SPONSORSHIPS, "all sponsorships must be SETTLED or WITHDRAWN")
    ev["status"] = "CLOSED"
    bump(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/cancel")
def cancel_event(eventId):
    authenticate(CEM)
    ev = _transition(
        eventId,
        ("PLANNING", "REGISTRATION_OPEN", "REGISTRATION_LOCKED"),
        "event cannot be cancelled from its current status",
    )
    event_cancel_cascade(ev)
    ev["status"] = "CANCELLED"
    bump(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/reschedule")
def reschedule_event(eventId):
    authenticate(CEM)
    ev = load_event(eventId)
    data = body()
    start_raw, end_raw, start, end = _parse_window(data)
    expected = req_int(data, "expected_event_version")
    # OCC (state, step 6) precedes temporal (step 9)
    if expected != ev["version"]:
        raise_err(ERR_STALE_EVENT_VERSION, "expected_event_version does not match current version")
    _check_window(start, end)
    ev["event_start_at"] = start_raw
    ev["event_end_at"] = end_raw
    ev["_start"] = start
    ev["_end"] = end
    bump(ev)
    from services.core import refresh_event

    refresh_event(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/bump-waiver-version")
def bump_waiver_version(eventId):
    authenticate(CEM)
    ev = load_event(eventId)
    ev["waiver_document_version"] += 1
    waiver_version_bump_cascade(ev, ev["waiver_document_version"])
    bump(ev)
    return success_object(ser_event(ev))


@bp.post("/service-events/<eventId>/rebook")
def rebook_event(eventId):
    authenticate(CEM)
    source = load_event(eventId)
    data = body()
    name = req_string(data, "name")
    start_raw = req_present(data, "event_start_at")
    end_raw = req_present(data, "event_end_at")
    start = parse_datetime(start_raw, "event_start_at")
    end = parse_datetime(end_raw, "event_end_at")
    budget = req_int(data, "budget_cents")
    if source["status"] not in ("COMPLETED", "CLOSED"):
        raise_err(ERR_REBOOK_NOT_ELIGIBLE, "source event must be COMPLETED or CLOSED")
    check_range(budget >= 0, "budget_cents must be >= 0")
    avg = calc.event_avg_feedback(source)
    bonus = (
        avg is not None
        and Decimal(str(avg)) >= calc.REPEAT_RATING_THRESHOLD
        and start <= source["_start"] + timedelta(days=calc.REPEAT_WINDOW_DAYS)
    )
    ev = mint()
    ev.update(
        {
            "name": name,
            "event_start_at": start_raw,
            "event_end_at": end_raw,
            "_start": start,
            "_end": end,
            "status": "PLANNING",
            "budget_cents": budget,
            "waiver_document_version": 1,
            "source_event_id": source["id"],
            "repeat_booking_bonus": bool(bonus),
        }
    )
    db.events[ev["id"]] = ev
    return success_object(ser_event(ev), 201)
