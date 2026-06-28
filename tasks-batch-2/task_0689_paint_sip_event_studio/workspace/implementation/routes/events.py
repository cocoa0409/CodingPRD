"""StudioEvent endpoints + lifecycle (PRD §3.2, §3.3, §3.10, §3.11)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import models
from clock import clock
from errors import err
from response import object_response, array_response
from services import calc, core

bp = Blueprint("events", __name__)

EVENT_TYPES = {"PUBLIC_CLASS", "PRIVATE_PARTY", "FUNDRAISER", "CORPORATE"}


def _windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: starts strictly before the other ends
    AND ends strictly after the other starts. Adjacency (end == start) is OK."""
    return a_start < b_end and a_end > b_start


def _check_studio_time_conflict(studio_id, start_dt, end_dt, exclude_event_id=None):
    """Reject if any other non-CANCELLED event in the same studio overlaps."""
    for e in db.events.values():
        if e["id"] == exclude_event_id:
            continue
        if e["studio_id"] != studio_id:
            continue
        if e["status"] == "CANCELLED":
            continue
        if _windows_overlap(start_dt, end_dt, e["_start_dt"], e["_end_dt"]):
            raise err(errors.ERR_STUDIO_TIME_CONFLICT,
                      "Studio room already has an overlapping event")


@bp.post("/studio-ops/events")
def create_event():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()

    # Priority 4: well-formedness (required fields, enums, integer bounds).
    studio_id = helpers.as_str(body, "studio_id")
    title = helpers.as_str(body, "title")
    event_type = helpers.as_enum(body, "event_type", EVENT_TYPES)
    start_dt = helpers.parse_datetime(body, "start_utc")
    end_dt = helpers.parse_datetime(body, "end_utc")
    seats_capacity = helpers.as_int(body, "seats_capacity", min_value=1)
    price = helpers.as_int(body, "price_cents_per_seat", min_value=0)
    kit_fee = helpers.as_int(body, "kit_fee_cents", required=False, default=0, min_value=0)
    byob = helpers.as_bool(body, "byob_allowed", required=False, default=False)
    min_age = helpers.as_int(body, "min_age", required=False, default=0, min_value=0)
    donation_pct = helpers.as_int(body, "fundraiser_donation_pct", required=False,
                                  default=0, min_value=0, max_value=100)

    # Priority 5: body-referenced FK (studio_id) must exist.
    studio = db.studios.get(studio_id)
    if not studio:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "studio_id does not exist")

    # Priority 19: event config validated as a unit (ERR_INVALID_EVENT_CONFIG).
    if seats_capacity > studio["room_capacity_seats"]:
        raise err(errors.ERR_INVALID_EVENT_CONFIG,
                  "seats_capacity exceeds studio room_capacity_seats")
    if not (end_dt > start_dt):
        raise err(errors.ERR_INVALID_EVENT_CONFIG, "end_utc must be after start_utc")
    if event_type == "FUNDRAISER":
        if not (1 <= donation_pct <= 100):
            raise err(errors.ERR_INVALID_EVENT_CONFIG,
                      "FUNDRAISER requires fundraiser_donation_pct in 1..100")
    else:
        if donation_pct != 0:
            raise err(errors.ERR_INVALID_EVENT_CONFIG,
                      "fundraiser_donation_pct must be 0 for non-FUNDRAISER events")

    # Priority 12: studio room time conflict.
    _check_studio_time_conflict(studio_id, start_dt, end_dt)

    rec = models.make_event(studio_id, title, event_type, start_dt, end_dt,
                            seats_capacity, price, kit_fee, byob, min_age,
                            donation_pct)
    db.events[rec["id"]] = rec
    return object_response(models.serialize_event(rec), 201)


@bp.get("/studio-ops/events/<eid>")
def get_event(eid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "Customer", "PlatformAdmin")
    rec = db.events.get(eid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Event not found")
    return object_response(models.serialize_event(rec), 200)


@bp.get("/studio-ops/events")
def list_events():
    middleware.authenticate()
    middleware.require_roles("StudioManager", "FrontDesk", "Customer", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    studio_id = request.args.get("studio_id")
    status = request.args.get("status")
    event_type = request.args.get("event_type")
    from_utc = request.args.get("from_utc")
    to_utc = request.args.get("to_utc")

    rows = list(db.events.values())
    if studio_id:
        rows = [r for r in rows if r["studio_id"] == studio_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if event_type:
        rows = [r for r in rows if r["event_type"] == event_type]
    if from_utc:
        f = helpers._parse_iso(from_utc, "from_utc")
        rows = [r for r in rows if r["_end_dt"] > f]
    if to_utc:
        t = helpers._parse_iso(to_utc, "to_utc")
        rows = [r for r in rows if r["_start_dt"] < t]

    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_event(r) for r in page],
                          limit, offset, total, 200)


@bp.post("/studio-ops/events/<eid>/schedule")
def schedule_event(eid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    event = db.events.get(eid)
    if not event:
        raise err(errors.ERR_NOT_FOUND, "Event not found")
    # State: must be DRAFT.
    if event["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Event is not in DRAFT")
    # Precondition: at least one ASSIGNED artist references the event.
    has_artist = any(
        a["event_id"] == eid and a["status"] == "ASSIGNED"
        for a in db.assignments.values()
    )
    if not has_artist:
        raise err(errors.ERR_INVALID_STATE,
                  "Event has no ASSIGNED artist assignment")
    # Precondition: hosting studio must be ACTIVE.
    studio = db.studios.get(event["studio_id"])
    if not studio or studio["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Hosting studio is not ACTIVE")
    # Precondition: re-check room-time conflict.
    _check_studio_time_conflict(event["studio_id"], event["_start_dt"],
                                event["_end_dt"], exclude_event_id=eid)
    event["status"] = "SCHEDULED"
    models.touch(event)
    return object_response(models.serialize_event(event), 200)


@bp.post("/studio-ops/events/<eid>/open")
def open_event(eid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    event = db.events.get(eid)
    if not event:
        raise err(errors.ERR_NOT_FOUND, "Event not found")
    if event["status"] != "SCHEDULED":
        raise err(errors.ERR_INVALID_STATE, "Event is not in SCHEDULED")
    event["status"] = "OPEN"
    models.touch(event)
    # Opening could immediately be FULL only if capacity already consumed; the
    # seat ledger is consistent already, so apply the flip for safety.
    core.apply_full_flip(event)
    return object_response(models.serialize_event(event), 200)


@bp.post("/studio-ops/events/<eid>/close")
def close_event(eid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    event = db.events.get(eid)
    if not event:
        raise err(errors.ERR_NOT_FOUND, "Event not found")
    # State: only OPEN/FULL may be closed.
    if event["status"] not in {"OPEN", "FULL"}:
        raise err(errors.ERR_INVALID_STATE, "Event is not OPEN/FULL")
    # Priority 8: clock now >= start_utc.
    if clock.now() < event["_start_dt"]:
        raise err(errors.ERR_EVENT_NOT_STARTED, "Event has not started yet")

    # Cascade: HELD/CONFIRMED reservations -> NO_SHOW (seats released).
    for r in core.event_reservations(eid):
        if r["status"] in {"HELD", "CONFIRMED"}:
            r["status"] = "NO_SHOW"
            models.touch(r)
    # Cascade: REGISTERED walk-ins -> CHECKED_IN.
    for w in core.event_walk_ins(eid):
        if w["status"] == "REGISTERED":
            w["status"] = "CHECKED_IN"
            models.touch(w)

    event["status"] = "CLOSED"
    core.recompute_seat_ledger(event)
    core.compute_settled_donation(event)
    # Pledged no longer recomputed after close.
    models.touch(event)
    return object_response(models.serialize_event(event), 200)


@bp.post("/studio-ops/events/<eid>/cancel")
def cancel_event(eid):
    middleware.authenticate()
    middleware.require_roles("StudioManager", "PlatformAdmin")
    event = db.events.get(eid)
    if not event:
        raise err(errors.ERR_NOT_FOUND, "Event not found")
    if event["status"] in {"CLOSED", "CANCELLED"}:
        raise err(errors.ERR_INVALID_STATE, "Event already terminal")

    # Full-credit cascade (studio-initiated; ladder bypassed, pct forced 100).
    for r in core.event_reservations(eid):
        if r["status"] in {"HELD", "CONFIRMED", "CHECKED_IN"}:
            # hop 1: 100% credit
            credit = r["total_cents"]
            r["credit_granted_cents"] = credit
            # cancelled_at_hours_before recorded against current clock.
            r["cancelled_at_hours_before"] = calc.hours_before(
                event["_start_dt"], clock.now())
            # hop 2: reverse CARD payments + REFUNDED
            core.reverse_card_payments_and_refund(r)
            # hop 3: credit the customer's wallet by total_cents
            cust = db.customers.get(r["customer_id"])
            if cust:
                cust["credit_balance_cents"] += credit
                models.touch(cust)
            r["status"] = "CANCELLED"
            models.touch(r)

    # ASSIGNED assignments -> RELEASED.
    for a in db.assignments.values():
        if a["event_id"] == eid and a["status"] == "ASSIGNED":
            a["status"] = "RELEASED"
            models.touch(a)
    # REGISTERED/CHECKED_IN walk-ins -> CANCELLED.
    for w in core.event_walk_ins(eid):
        if w["status"] in {"REGISTERED", "CHECKED_IN"}:
            w["status"] = "CANCELLED"
            models.touch(w)

    event["status"] = "CANCELLED"
    core.recompute_seat_ledger(event)
    core.recompute_pledged_donation(event)
    models.touch(event)
    return object_response(models.serialize_event(event), 200)
