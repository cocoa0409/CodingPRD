"""Venues and session slots."""
from flask import Blueprint

import calc
import domain
import store
import web
from core import Field, as_dt, authenticate, bad_request, fail, parse_body
from web import PREFIX

bp = Blueprint("schedule", __name__)

VENUE_FIELDS = [
    Field("games_edition_id", "id"),
    Field("name", "str"),
    Field("competition_area_count", "int", minimum=1),
    Field("spectator_capacity", "int", minimum=0),
    Field("emergency_protocol_code", "str",
          enum=("EP_BASIC", "EP_ADVANCED", "EP_CARDIAC")),
    Field("has_onsite_medical_bay", "bool", required=False, default=False),
]


@bp.post(PREFIX + "/venues")
def create_venue():
    authenticate("GamesAdmin")
    body = parse_body(VENUE_FIELDS)
    store.must_get("games_edition", body["games_edition_id"])
    row = store.insert(
        "venue",
        {
            "games_edition_id": body["games_edition_id"],
            "name": body["name"],
            "competition_area_count": body["competition_area_count"],
            "spectator_capacity": body["spectator_capacity"],
            "has_onsite_medical_bay": body["has_onsite_medical_bay"],
            "emergency_protocol_code": body["emergency_protocol_code"],
            "status": "OPEN",
            "closed_reason": None,
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/venues/<venue_id>")
def read_venue(venue_id):
    return web.single("venue", venue_id)


@bp.get(PREFIX + "/venues")
def list_venues():
    return web.collection("venue", ("games_edition_id", "status"))


@bp.post(PREFIX + "/venues/<venue_id>/close")
def close_venue(venue_id):
    authenticate("GamesAdmin")
    body = parse_body([Field("reason", "str", allow_empty=True)])
    venue = store.must_get("venue", venue_id)
    web.guard_state(venue["status"], ("OPEN",))
    venue["status"] = "CLOSED"
    venue["closed_reason"] = body["reason"]
    store.touch(venue)
    touched_events = []
    for slot in domain.slots_of_venue(venue["id"], domain.OCCUPYING_SLOT_STATES):
        domain.displace_slot(slot)
        event = store.get("sport_event", slot["sport_event_id"])
        if event is not None and event not in touched_events:
            touched_events.append(event)
    for event in touched_events:
        if event["status"] != "SEEDED":
            continue
        own_slots = domain.slots_of_event(event["id"])
        if not own_slots:
            continue
        if any(s["status"] in domain.OCCUPYING_SLOT_STATES for s in own_slots):
            continue
        event["status"] = "SCHEDULE_HOLD"
        store.touch(event)
    return web.obj(venue)


SLOT_FIELDS = [
    Field("venue_id", "id"),
    Field("sport_event_id", "id"),
    Field("start_utc", "datetime"),
    Field("end_utc", "datetime"),
    Field("teardown_buffer_minutes", "int", required=False, default=15,
          minimum=0, maximum=120),
    Field("required_official_count", "int", required=False, default=2, minimum=1),
]


def _slot_safety_gates(venue, event):
    if venue["status"] != "OPEN":
        fail("ERR_VENUE_CLOSED")
    sport = domain.sport_of_event(event)
    if sport is not None and sport["contact_class"] == "HIGH":
        if not venue["has_onsite_medical_bay"]:
            fail("ERR_MEDICAL_COVERAGE_REQUIRED")
    if calc.band_floor(event["age_group_code"]) >= calc.CARDIAC_PROTOCOL_BAND_FLOOR:
        if venue["emergency_protocol_code"] != "EP_CARDIAC":
            fail("ERR_EMERGENCY_PROTOCOL_INSUFFICIENT")


@bp.post(PREFIX + "/session-slots")
def create_session_slot():
    authenticate("GamesAdmin")
    body = parse_body(SLOT_FIELDS)
    venue = store.must_get("venue", body["venue_id"])
    event = store.must_get("sport_event", body["sport_event_id"])
    start = as_dt(body["start_utc"])
    end = as_dt(body["end_utc"])
    buffer_minutes = body["teardown_buffer_minutes"]
    _slot_safety_gates(venue, event)
    domain.slot_recovery_gate(event, (start, end))
    domain.venue_area_gate(venue, start, end, buffer_minutes)
    if end <= start:
        bad_request("end_utc must be strictly after start_utc")
    row = store.insert(
        "session_slot",
        {
            "venue_id": body["venue_id"],
            "sport_event_id": body["sport_event_id"],
            "start_utc": body["start_utc"],
            "end_utc": body["end_utc"],
            "teardown_buffer_minutes": buffer_minutes,
            "required_official_count": body["required_official_count"],
            "confirmed_official_count": 0,
            "status": "SCHEDULED",
        },
    )
    return web.obj(row, 201)


@bp.get(PREFIX + "/session-slots/<session_slot_id>")
def read_session_slot(session_slot_id):
    return web.single("session_slot", session_slot_id)


@bp.get(PREFIX + "/session-slots")
def list_session_slots():
    return web.collection("session_slot", ("venue_id", "sport_event_id", "status"))


RESCHEDULE_FIELDS = [
    Field("venue_id", "id"),
    Field("start_utc", "datetime"),
    Field("end_utc", "datetime"),
    Field("teardown_buffer_minutes", "int", required=False, default=15,
          minimum=0, maximum=120),
]


@bp.post(PREFIX + "/session-slots/<session_slot_id>/reschedule")
def reschedule_session_slot(session_slot_id):
    authenticate("GamesAdmin")
    body = parse_body(RESCHEDULE_FIELDS)
    slot = store.must_get("session_slot", session_slot_id)
    venue = store.must_get("venue", body["venue_id"])
    web.guard_state(slot["status"], ("DISPLACED",))
    event = store.get("sport_event", slot["sport_event_id"])
    start = as_dt(body["start_utc"])
    end = as_dt(body["end_utc"])
    buffer_minutes = body["teardown_buffer_minutes"]
    _slot_safety_gates(venue, event)
    if event is not None:
        domain.slot_recovery_gate(event, (start, end), exclude_slot_id=slot["id"])
    domain.venue_area_gate(
        venue, start, end, buffer_minutes, exclude_slot_id=slot["id"]
    )
    if end <= start:
        bad_request("end_utc must be strictly after start_utc")
    slot["venue_id"] = body["venue_id"]
    slot["start_utc"] = body["start_utc"]
    slot["end_utc"] = body["end_utc"]
    slot["teardown_buffer_minutes"] = buffer_minutes
    slot["status"] = "SCHEDULED"
    store.touch(slot)
    if event is not None and event["status"] == "SCHEDULE_HOLD":
        event["status"] = "SEEDED"
        store.touch(event)
    return web.obj(slot)


@bp.post(PREFIX + "/session-slots/<session_slot_id>/advance")
def advance_session_slot(session_slot_id):
    authenticate("GamesAdmin")
    body = parse_body([Field("to_status", "str", enum=("IN_PROGRESS", "COMPLETED"))])
    slot = store.must_get("session_slot", session_slot_id)
    target = body["to_status"]
    origin = "SCHEDULED" if target == "IN_PROGRESS" else "IN_PROGRESS"
    web.guard_state(slot["status"], (origin,))
    venue = store.get("venue", slot["venue_id"])
    if venue is not None and venue["status"] != "OPEN":
        fail("ERR_VENUE_CLOSED")
    event = store.get("sport_event", slot["sport_event_id"])
    if target == "IN_PROGRESS":
        if event is None or event["status"] not in ("SEEDED", "IN_PROGRESS"):
            fail("ERR_INVALID_STATE_TRANSITION", "The slot's event is not ready to run")
        if slot["confirmed_official_count"] < slot["required_official_count"]:
            fail("ERR_INVALID_STATE_TRANSITION", "The slot is short of confirmed officials")
        if store.CLOCK.now() < as_dt(slot["start_utc"]):
            fail("ERR_INVALID_STATE_TRANSITION", "The slot's start instant has not arrived")
        slot["status"] = "IN_PROGRESS"
        store.touch(slot)
        if event["status"] == "SEEDED":
            event["status"] = "IN_PROGRESS"
            store.touch(event)
    else:
        domain.complete_slot(slot)
    return web.obj(slot)
