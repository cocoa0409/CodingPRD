"""Event and EventRSVP endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from clock import CLOCK, iso_format, parse_iso
from db import DB, stamp_new, bump
from errors import (
    InvalidRequest,
    NotFound,
    ReferenceNotFound,
    Forbidden,
    NotVerifiedInNeighborhood,
    InvalidTimeWindow,
    InvalidState,
    LocationOutsideGeofence,
    GroupEventCapacity,
    EventFull,
)
from geo import point_inside
from middleware import require_roles
from paging import apply_pagination
from response import success
from validators import as_str, as_int, as_number, as_enum


bp = Blueprint("events", __name__)

RSVP_STATUSES = {"YES", "NO", "MAYBE"}
ALL_ROLES = ("Resident", "Moderator", "BusinessOwner", "AgencyOfficer", "PlatformAdmin")


def _resident_verified_in(neighborhood_id: str, resident_id: str) -> bool:
    for m in DB.resident_memberships.values():
        if (
            m["resident_id"] == resident_id
            and m["neighborhood_id"] == neighborhood_id
            and m["status"] == "VERIFIED"
        ):
            return True
    return False


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


@bp.post("/neighborhood/events")
@require_roles("Resident", "Moderator")
def create_event():
    payload = request.get_json(silent=True) or {}
    group_id = as_str(payload, "group_id")
    neighborhood_id = as_str(payload, "neighborhood_id")
    title = as_str(payload, "title")
    venue_lat = as_number(payload, "venue_lat")
    venue_lng = as_number(payload, "venue_lng")
    starts_at_str = as_str(payload, "starts_at")
    ends_at_str = as_str(payload, "ends_at")
    capacity = as_int(payload, "capacity")

    grp = DB.groups.get(group_id)
    if grp is None:
        raise ReferenceNotFound(f"Group {group_id} not found")
    n = DB.neighborhoods.get(neighborhood_id)
    if n is None:
        raise ReferenceNotFound(f"Neighborhood {neighborhood_id} not found")

    if grp["neighborhood_id"] != neighborhood_id:
        raise InvalidRequest("Event.neighborhood_id must equal Group.neighborhood_id")

    if not _resident_verified_in(neighborhood_id, g.user_id):
        raise NotVerifiedInNeighborhood(
            "Acting resident is not verified in the target neighborhood"
        )

    try:
        starts_at = parse_iso(starts_at_str)
        ends_at = parse_iso(ends_at_str)
    except ValueError:
        raise InvalidRequest("starts_at/ends_at must be ISO 8601 timestamps")

    now = CLOCK.now()
    if not (starts_at > now and ends_at > starts_at):
        raise InvalidTimeWindow("Event time window invalid")

    if not (1 <= capacity <= 500):
        raise InvalidRequest("capacity must be between 1 and 500")

    if not point_inside(n, venue_lat, venue_lng):
        raise LocationOutsideGeofence("venue coordinates outside neighborhood geofence")

    # Group event capacity (priority 131): count SCHEDULED overlapping events (including the proposed).
    overlapping = 0
    for e in DB.events.values():
        if e["group_id"] != group_id:
            continue
        if e["state"] != "SCHEDULED":
            continue
        e_start = parse_iso(e["starts_at"])
        e_end = parse_iso(e["ends_at"])
        if _intervals_overlap(starts_at, ends_at, e_start, e_end):
            overlapping += 1
    # Including the proposed event, must not exceed 3.
    if overlapping + 1 > 3:
        raise GroupEventCapacity(
            "More than 3 concurrent SCHEDULED events on this group"
        )

    e = {
        "group_id": group_id,
        "neighborhood_id": neighborhood_id,
        "title": title,
        "venue_lat": venue_lat,
        "venue_lng": venue_lng,
        "starts_at": iso_format(starts_at),
        "ends_at": iso_format(ends_at),
        "capacity": capacity,
        "rsvp_count": 0,
        "state": "SCHEDULED",
    }
    stamp_new(e)
    DB.events[e["id"]] = e
    return success(e, status=201)


@bp.get("/neighborhood/events/<eid>")
@require_roles(*ALL_ROLES)
def get_event(eid: str):
    e = DB.events.get(eid)
    if e is None:
        raise NotFound(f"Event {eid} not found")
    return success(e)


@bp.get("/neighborhood/events")
@require_roles(*ALL_ROLES)
def list_events():
    gid = request.args.get("group_id")
    nid = request.args.get("neighborhood_id")
    state = request.args.get("state")
    rows = list(DB.events.values())
    if gid is not None:
        rows = [r for r in rows if r["group_id"] == gid]
    if nid is not None:
        rows = [r for r in rows if r["neighborhood_id"] == nid]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)


@bp.post("/neighborhood/events/<eid>/cancel")
@require_roles("Resident", "Moderator")
def cancel_event(eid: str):
    e = DB.events.get(eid)
    if e is None:
        raise NotFound(f"Event {eid} not found")
    if e["state"] != "SCHEDULED":
        raise InvalidState(f"Event.state is {e['state']}, expected SCHEDULED")
    grp = DB.groups.get(e["group_id"])
    if grp is None:
        raise NotFound("Hosting group not found")
    if grp["creator_resident_id"] != g.user_id:
        raise Forbidden("Only the group's creator may cancel this event")

    e["state"] = "CANCELLED"
    bump(e)
    # Delete every EventRSVP row for this event; rsvp_count -> 0
    to_delete = [rid for rid, r in DB.event_rsvps.items() if r["event_id"] == eid]
    for rid in to_delete:
        del DB.event_rsvps[rid]
    e["rsvp_count"] = 0
    bump(e)
    return success(e)


# --------------------------------------------------------------- EventRSVP

@bp.post("/neighborhood/event-rsvps")
@require_roles("Resident", "Moderator")
def create_rsvp():
    payload = request.get_json(silent=True) or {}
    event_id = as_str(payload, "event_id")
    resident_id = as_str(payload, "resident_id")
    rsvp_status = as_enum(payload, "rsvp_status", RSVP_STATUSES)

    event = DB.events.get(event_id)
    if event is None:
        raise ReferenceNotFound(f"Event {event_id} not found")
    if DB.residents.get(resident_id) is None:
        raise ReferenceNotFound(f"Resident {resident_id} not found")

    # State check first (priority 70)
    if event["state"] in ("CANCELLED", "COMPLETED"):
        raise InvalidState(f"Event.state is {event['state']}, cannot RSVP")

    # Find existing RSVP
    existing = None
    for r in DB.event_rsvps.values():
        if r["event_id"] == event_id and r["resident_id"] == resident_id:
            existing = r
            break

    prev_status = existing["rsvp_status"] if existing else None
    going_yes = rsvp_status == "YES"
    was_yes = prev_status == "YES"
    increment = going_yes and not was_yes
    decrement = (not going_yes) and was_yes

    # Capacity check on increment (event_capacity_reservation)
    if increment:
        if event.get("rsvp_count", 0) >= event["capacity"]:
            raise EventFull("Event capacity reached")

    if existing is None:
        row = {
            "event_id": event_id,
            "resident_id": resident_id,
            "rsvp_status": rsvp_status,
        }
        stamp_new(row)
        DB.event_rsvps[row["id"]] = row
    else:
        existing["rsvp_status"] = rsvp_status
        bump(existing)
        row = existing

    if increment:
        event["rsvp_count"] = event.get("rsvp_count", 0) + 1
        bump(event)
    elif decrement:
        event["rsvp_count"] = max(0, event.get("rsvp_count", 0) - 1)
        bump(event)

    status = 201 if existing is None else 200
    return success(row, status=status)


@bp.get("/neighborhood/event-rsvps/<rid>")
@require_roles("Resident", "Moderator", "PlatformAdmin")
def get_rsvp(rid: str):
    r = DB.event_rsvps.get(rid)
    if r is None:
        raise NotFound(f"EventRSVP {rid} not found")
    return success(r)


@bp.get("/neighborhood/event-rsvps")
@require_roles("Resident", "Moderator", "PlatformAdmin")
def list_rsvps():
    eid = request.args.get("event_id")
    rid = request.args.get("resident_id")
    status = request.args.get("rsvp_status")
    rows = list(DB.event_rsvps.values())
    if eid is not None:
        rows = [r for r in rows if r["event_id"] == eid]
    if rid is not None:
        rows = [r for r in rows if r["resident_id"] == rid]
    if status is not None:
        rows = [r for r in rows if r["rsvp_status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, meta = apply_pagination(rows)
    return success(page, response_type="array", pagination=meta)
