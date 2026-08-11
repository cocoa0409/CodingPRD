"""Campus registry events, seat bookings, and fee-waiver minting (PRD §3.9)."""
import uuid

from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import event_view, registration_view
from response import list_response, ok_object
from routes.common import field, load

bp = Blueprint("events", __name__)


@bp.post("/registry/events")
@require_roles("Admin")
def create_event():
    data = body()
    host_org_id = field(data, "host_org_id", "string", required=True)
    title = field(data, "title", "string", required=True)
    venue = field(data, "venue", "string", required=True)
    starts_at = field(data, "starts_at", "datetime", required=True)
    ends_at = field(data, "ends_at", "datetime", required=True)
    capacity = field(data, "capacity", "integer", required=True, min_value=1)
    if starts_at >= ends_at:
        fail("ERR_INVALID_REQUEST", "starts_at must precede ends_at")

    org = load(db.partner_orgs, host_org_id, "ERR_PARTNER_ORG_NOT_FOUND")
    if org["org_type"] != "CAMPUS":
        fail("ERR_EVENT_HOST_NOT_CAMPUS", "The host organization must be a CAMPUS org")
    if org["status"] != "ACTIVE":
        fail("ERR_PARTNER_ORG_NOT_ACTIVE", "The host organization is not ACTIVE")

    rec = db.new_record({
        "host_org_id": host_org_id,
        "title": title,
        "venue": venue,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "registered_count": 0,
        "status": "DRAFT",
    })
    db.events[rec["id"]] = rec
    return ok_object(event_view(rec), status=201)


@bp.get("/registry/events")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def list_events():
    recs = list(db.events.values())
    for param, key in (("host_org_id", "host_org_id"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [e for e in recs if e[key] == value]
    return list_response(recs, event_view)


@bp.get("/registry/events/<event_id>")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def read_event(event_id):
    rec = load(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    return ok_object(event_view(rec))


@bp.post("/registry/events/<event_id>/publish")
@require_roles("Admin")
def publish_event(event_id):
    rec = load(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    if rec["status"] != "DRAFT":
        fail("ERR_EVENT_NOT_PUBLISHED", "Only a DRAFT event can be published")
    # Half-open windows: overlap iff new.starts < existing.ends AND
    # existing.starts < new.ends; touching endpoints do NOT overlap.
    for other in db.events.values():
        if (other["id"] != rec["id"] and other["host_org_id"] == rec["host_org_id"]
                and other["status"] == "PUBLISHED"
                and rec["starts_at"] < other["ends_at"]
                and other["starts_at"] < rec["ends_at"]):
            fail("ERR_EVENT_WINDOW_OVERLAP",
                 "Window overlaps another PUBLISHED event of this host")
    rec["status"] = "PUBLISHED"
    db.bump(rec)
    return ok_object(event_view(rec))


@bp.post("/registry/events/<event_id>/complete")
@require_roles("Admin")
def complete_event(event_id):
    rec = load(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    if rec["status"] != "PUBLISHED":
        fail("ERR_EVENT_NOT_PUBLISHED", "Only a PUBLISHED event can be completed")
    if db.now() < rec["ends_at"]:
        fail("ERR_EVENT_ENDED", "The event window has not ended")
    rec["status"] = "COMPLETED"
    db.bump(rec)
    return ok_object(event_view(rec))


@bp.post("/registry/events/<event_id>/cancel")
@require_roles("Admin")
def cancel_event(event_id):
    rec = load(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    if rec["status"] == "DRAFT":
        rec["status"] = "CANCELLED"
        db.bump(rec)
        return ok_object(event_view(rec))
    if rec["status"] != "PUBLISHED":
        fail("ERR_EVENT_NOT_PUBLISHED", "Event cannot be cancelled from its state")

    # Cascade: BOOKED registrations -> CANCELLED, registered_count -> 0, and
    # unused waiver codes become invalid (event CANCELLED fails waiver validity).
    for reg in db.event_registrations.values():
        if reg["event_id"] == rec["id"] and reg["status"] == "BOOKED":
            reg["status"] = "CANCELLED"
            db.bump(reg)
    rec["registered_count"] = 0
    rec["status"] = "CANCELLED"
    db.bump(rec)
    return ok_object(event_view(rec))


@bp.post("/registry/events/<event_id>/registrations")
@require_roles("Owner")
def book_seat(event_id):
    rec = load(db.events, event_id, "ERR_EVENT_NOT_FOUND")
    if rec["status"] != "PUBLISHED":
        fail("ERR_EVENT_NOT_PUBLISHED", "Seats can be booked only on PUBLISHED events")
    # Stage 12 uniqueness precedes stage 14 temporal and stage 15 capacity.
    if any(r["event_id"] == rec["id"] and r["owner_id"] == g.user_id and r["status"] == "BOOKED"
           for r in db.event_registrations.values()):
        fail("ERR_EVENT_REGISTRATION_EXISTS", "You already hold a booking at this event")
    if db.now() >= rec["ends_at"]:
        fail("ERR_EVENT_ENDED", "The event window has ended")
    if rec["registered_count"] >= rec["capacity"]:
        fail("ERR_EVENT_CAPACITY_FULL", "The event is at capacity")

    reg = db.new_record({
        "event_id": rec["id"],
        "owner_id": g.user_id,
        "status": "BOOKED",
        "waiver_code": "WVR-" + uuid.uuid4().hex[:16],
        "waiver_used": False,
    })
    db.event_registrations[reg["id"]] = reg
    rec["registered_count"] += 1
    db.bump(rec)
    return ok_object(registration_view(reg), status=201)


@bp.get("/registry/event-registrations")
@require_roles("Owner", "Registrar", "Admin")
def list_registrations():
    recs = list(db.event_registrations.values())
    if g.role == "Owner":
        recs = [r for r in recs if r["owner_id"] == g.user_id]
    for param, key in (("event_id", "event_id"), ("owner_id", "owner_id"),
                       ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [r for r in recs if r[key] == value]
    return list_response(recs, registration_view)


@bp.get("/registry/event-registrations/<reg_id>")
@require_roles("Owner", "Registrar", "Admin")
def read_registration(reg_id):
    rec = load(db.event_registrations, reg_id, "ERR_EVENT_REGISTRATION_NOT_FOUND")
    if g.role == "Owner" and rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only their own registrations")
    return ok_object(registration_view(rec))


@bp.post("/registry/event-registrations/<reg_id>/cancel")
@require_roles("Owner")
def cancel_registration(reg_id):
    rec = load(db.event_registrations, reg_id, "ERR_EVENT_REGISTRATION_NOT_FOUND")
    if rec["owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the booking's owner may cancel it")
    if rec["status"] != "BOOKED":
        fail("ERR_EVENT_NOT_PUBLISHED", "Only a BOOKED registration can be cancelled")
    rec["status"] = "CANCELLED"
    db.bump(rec)
    event = db.events.get(rec["event_id"])
    if event is not None:
        event["registered_count"] = max(0, event["registered_count"] - 1)
        db.bump(event)
    return ok_object(registration_view(rec))
