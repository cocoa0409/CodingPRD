"""Events and event registrations (PRD §3.6)."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_REGISTERED,
    ERR_FORMS_INCOMPLETE,
    ERR_MEMBER_DOUBLE_BOOKED,
    ERR_EVENT_FULL,
)
from middleware import authenticate, require_roles, BOTH_ROLES, LEADER_ONLY
from response import object_response, array_response
from serializers import serialize_event, serialize_event_registration
from util import new_id, iso_now, parse_iso_datetime
from routes import helpers as h
from services import recompute

bp = Blueprint("events", __name__)


@bp.post("/troops/<troop_id>/events")
def create_event(troop_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    troop = h.get_or_404(db.troops, troop_id)
    body = h.get_json_body()

    title = h.require_string(body, "title")
    starts_raw = h.require_string(body, "starts_at")
    ends_raw = h.require_string(body, "ends_at")
    capacity = h.require_int(body, "capacity")
    requires_health_form = h.optional_bool(body, "requires_health_form", True)

    starts_at = parse_iso_datetime(starts_raw)
    ends_at = parse_iso_datetime(ends_raw)
    # ends_at strictly after starts_at (PRD §3.6).
    if not (ends_at > starts_at):
        raise err(ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    if capacity < 1:
        raise err(ERR_INVALID_REQUEST, "capacity must be >= 1")

    now = iso_now(datetime.now(timezone.utc))
    event = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "troop_id": troop["id"],
        "title": title,
        "starts_at": iso_now(starts_at),
        "ends_at": iso_now(ends_at),
        "_starts_dt": starts_at,
        "_ends_dt": ends_at,
        "requires_health_form": requires_health_form,
        "capacity": capacity,
        "confirmed_count": 0,
        "status": "OPEN",
        "_seq": db.next_seq(),
    }
    db.events[event["id"]] = event
    return object_response(serialize_event(event), status=201)


@bp.get("/events/<event_id>")
def get_event(event_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    event = h.get_or_404(db.events, event_id)
    recompute.refresh_event_read(event)
    return object_response(serialize_event(event))


@bp.get("/events")
def list_events():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    troop_id = request.args.get("troop_id")
    status = request.args.get("status")
    limit, offset = h.parse_pagination()
    rows = [
        e for e in db.events.values()
        if (troop_id is None or e["troop_id"] == troop_id)
        and (status is None or e["status"] == status)
    ]
    rows = h.sort_by_creation(rows)
    for e in rows:
        recompute.refresh_event_read(e)
    page, total = h.paginate(rows, limit, offset)
    return array_response([serialize_event(e) for e in page], limit, offset, total)


@bp.post("/events/<event_id>/lock")
def lock_event(event_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    event = h.get_or_404(db.events, event_id)
    if event["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "lock only from OPEN")
    event["status"] = "LOCKED"
    h.touch_and_bump(event)
    return object_response(serialize_event(event))


@bp.post("/events/<event_id>/cancel")
def cancel_event(event_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    event = h.get_or_404(db.events, event_id)
    # Cancel permitted from OPEN or LOCKED (PRD §3.6).
    if event["status"] not in ("OPEN", "LOCKED"):
        raise err(ERR_INVALID_STATE, "cancel only from OPEN or LOCKED")
    event["status"] = "CANCELLED"
    # Cascade every registration in HOLD or CONFIRMED -> CANCELLED.
    for r in db.event_registrations.values():
        if r["event_id"] == event["id"] and r["status"] in ("HOLD", "CONFIRMED"):
            r["status"] = "CANCELLED"
            h.touch_and_bump(r)
    event["confirmed_count"] = 0
    h.touch_and_bump(event)
    return object_response(serialize_event(event))


# ---------------------------------------------------------------------------
# Event registrations
# ---------------------------------------------------------------------------
reg_bp = Blueprint("event_registrations", __name__)


@bp.post("/events/<event_id>/registrations")
def create_registration(event_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    event = h.get_or_404(db.events, event_id)
    body = h.get_json_body()
    member_id = h.require_string(body, "member_id")

    # Body FK: member_id must exist (PRD §2.7) -> ERR_INVALID_REFERENCE.
    if member_id not in db.members:
        raise err(ERR_INVALID_REFERENCE, "member_id does not exist")

    now = iso_now(datetime.now(timezone.utc))
    reg = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "event_id": event["id"],
        "member_id": member_id,
        "permission_status": "UNSIGNED",
        "health_status": "MISSING",
        "status": "HOLD",
        "_seq": db.next_seq(),
    }
    db.event_registrations[reg["id"]] = reg
    return object_response(serialize_event_registration(reg), status=201)


@reg_bp.get("/event-registrations/<reg_id>")
def get_registration(reg_id):
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    reg = h.get_or_404(db.event_registrations, reg_id)
    return object_response(serialize_event_registration(reg))


@reg_bp.get("/event-registrations")
def list_registrations():
    _, role = authenticate()
    require_roles(role, BOTH_ROLES)
    event_id = request.args.get("event_id")
    member_id = request.args.get("member_id")
    limit, offset = h.parse_pagination()
    rows = [
        r for r in db.event_registrations.values()
        if (event_id is None or r["event_id"] == event_id)
        and (member_id is None or r["member_id"] == member_id)
    ]
    rows = h.sort_by_creation(rows)
    page, total = h.paginate(rows, limit, offset)
    return array_response(
        [serialize_event_registration(r) for r in page], limit, offset, total
    )


@reg_bp.post("/event-registrations/<reg_id>/sign-permission")
def sign_permission(reg_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    reg = h.get_or_404(db.event_registrations, reg_id)
    # Permitted only while on HOLD, permission still UNSIGNED (PRD §3.6).
    if reg["status"] != "HOLD" or reg["permission_status"] != "UNSIGNED":
        raise err(ERR_INVALID_STATE, "sign-permission requires HOLD + UNSIGNED")
    reg["permission_status"] = "SIGNED"
    h.touch_and_bump(reg)
    return object_response(serialize_event_registration(reg))


@reg_bp.post("/event-registrations/<reg_id>/file-health")
def file_health(reg_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    reg = h.get_or_404(db.event_registrations, reg_id)
    if reg["status"] != "HOLD" or reg["health_status"] != "MISSING":
        raise err(ERR_INVALID_STATE, "file-health requires HOLD + MISSING")
    reg["health_status"] = "ON_FILE"
    h.touch_and_bump(reg)
    return object_response(serialize_event_registration(reg))


@reg_bp.post("/event-registrations/<reg_id>/confirm")
def confirm_registration(reg_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    reg = h.get_or_404(db.event_registrations, reg_id)
    event = db.events[reg["event_id"]]

    # State: registration must be HOLD; event must be OPEN (LOCKED freezes
    # confirmations) -> ERR_INVALID_STATE (PRD §3.6).
    if reg["status"] != "HOLD":
        raise err(ERR_INVALID_STATE, "confirm only from HOLD")
    if event["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "event is not OPEN")

    # Member must be REGISTERED (PRD §3.6) -> ERR_MEMBER_NOT_REGISTERED.
    member = db.members.get(reg["member_id"])
    if member is None or member["registration_status"] != "REGISTERED":
        raise err(ERR_MEMBER_NOT_REGISTERED, "member must be REGISTERED to confirm")

    # Forms: permission SIGNED, and health ON_FILE if required (PRD §3.6).
    if reg["permission_status"] != "SIGNED":
        raise err(ERR_FORMS_INCOMPLETE, "permission form not signed")
    if event["requires_health_form"] and reg["health_status"] != "ON_FILE":
        raise err(ERR_FORMS_INCOMPLETE, "required health form not on file")

    # Member double-booking: no two CONFIRMED registrations whose events'
    # [starts_at, ends_at] CLOSED intervals overlap or touch (PRD §3.6).
    if _has_time_collision(member["id"], event, exclude_reg_id=reg["id"]):
        raise err(ERR_MEMBER_DOUBLE_BOOKED, "member has an overlapping confirmed event")

    # Capacity (PRD §3.6) -> ERR_EVENT_FULL.
    confirmed = recompute.compute_event_confirmed_count(event["id"])
    if confirmed >= event["capacity"]:
        raise err(ERR_EVENT_FULL, "event is at capacity")

    reg["status"] = "CONFIRMED"
    h.touch_and_bump(reg)
    event["confirmed_count"] = recompute.compute_event_confirmed_count(event["id"])
    h.touch_and_bump(event)
    return object_response(serialize_event_registration(reg))


def _has_time_collision(member_id, target_event, exclude_reg_id):
    """True if member has another CONFIRMED reg whose event window collides.

    Closed-interval, touch-rejecting: windows collide if start <= other_end and
    other_start <= end (a zero gap is a collision).
    """
    t_start = target_event["_starts_dt"]
    t_end = target_event["_ends_dt"]
    for r in db.event_registrations.values():
        if r["id"] == exclude_reg_id:
            continue
        if r["member_id"] != member_id or r["status"] != "CONFIRMED":
            continue
        other = db.events.get(r["event_id"])
        if other is None:
            continue
        o_start = other["_starts_dt"]
        o_end = other["_ends_dt"]
        # Closed intervals overlap-or-touch.
        if t_start <= o_end and o_start <= t_end:
            return True
    return False


@reg_bp.post("/event-registrations/<reg_id>/cancel")
def cancel_registration(reg_id):
    _, role = authenticate()
    require_roles(role, LEADER_ONLY)
    reg = h.get_or_404(db.event_registrations, reg_id)
    # Cancel defined from CONFIRMED or HOLD (PRD §3.6).
    if reg["status"] not in ("CONFIRMED", "HOLD"):
        raise err(ERR_INVALID_STATE, "cancel only from CONFIRMED or HOLD")
    was_confirmed = reg["status"] == "CONFIRMED"
    reg["status"] = "CANCELLED"
    h.touch_and_bump(reg)
    if was_confirmed:
        event = db.events[reg["event_id"]]
        event["confirmed_count"] = recompute.compute_event_confirmed_count(event["id"])
        h.touch_and_bump(event)
    return object_response(serialize_event_registration(reg))
