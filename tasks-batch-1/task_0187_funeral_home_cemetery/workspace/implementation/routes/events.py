import datetime

from flask import Blueprint, request

import db
import errors
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("events", __name__)


def _parse_dt(value, field):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("%s must be an ISO 8601 datetime string" % field)
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except ValueError:
        raise errors.invalid_request("%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


@bp.post("/cases/<case_id>/events")
@require("Arranger")
def create_event(case_id):
    case = lookup.case(case_id)
    body = validate.get_json()
    resource_kind = validate.require_enum(body, "resource_kind", {"CHAPEL", "GRAVESIDE"})
    resource_id = validate.require_string(body, "resource_id")
    starts_at_raw = validate.require_string(body, "starts_at")
    starts_at = _parse_dt(starts_at_raw, "starts_at")

    if resource_kind == "CHAPEL":
        ends_at_raw = body.get("ends_at")
        if ends_at_raw is None:
            raise errors.invalid_request("CHAPEL events require ends_at")
        ends_at = _parse_dt(ends_at_raw, "ends_at")
        # resource is a Venue
        venue = lookup.venue(resource_id)
        home = db.funeral_homes.get(venue["funeral_home_id"])
        buffer_minutes = home.get("chapel_buffer_minutes", 30) if home else 30
        _check_chapel_conflict(resource_id, starts_at, ends_at, buffer_minutes)
        stored_ends = ends_at_raw
    else:  # GRAVESIDE
        # resource is a Plot; whole-day exclusivity; ends_at ignored
        lookup.plot(resource_id)
        _check_graveside_conflict(resource_id, starts_at)
        ends_at_raw = body.get("ends_at")
        stored_ends = None

    event = {
        "id": db.new_id(),
        "case_id": case_id,
        "resource_kind": resource_kind,
        "resource_id": resource_id,
        "starts_at": starts_at_raw,
        "ends_at": stored_ends,
        "status": "SCHEDULED",
    }
    db.stamp_create(event)
    db.events[event["id"]] = event
    return ok_object(serialize.event(event), 201)


def _check_chapel_conflict(venue_id, starts_at, ends_at, buffer_minutes):
    buf = datetime.timedelta(minutes=buffer_minutes)
    for e in db.events.values():
        if e["status"] != "SCHEDULED":
            continue
        if e["resource_kind"] != "CHAPEL" or e["resource_id"] != venue_id:
            continue
        e_start = _parse_dt(e["starts_at"], "starts_at")
        e_end = _parse_dt(e["ends_at"], "ends_at")
        # extend each existing interval's end by the buffer (cleanup between
        # consecutive bookings); also extend the new interval symmetrically so
        # an existing booking starting just after the new one collides too.
        if _intervals_overlap(starts_at, ends_at + buf, e_start, e_end + buf):
            raise errors.conflict(errors.ERR_SCHEDULE_CONFLICT,
                                  "Chapel booking conflicts with an existing event")


def _check_graveside_conflict(plot_id, starts_at):
    target_date = starts_at.astimezone(datetime.timezone.utc).date()
    for e in db.events.values():
        if e["status"] != "SCHEDULED":
            continue
        if e["resource_kind"] != "GRAVESIDE" or e["resource_id"] != plot_id:
            continue
        e_start = _parse_dt(e["starts_at"], "starts_at")
        if e_start.astimezone(datetime.timezone.utc).date() == target_date:
            raise errors.conflict(errors.ERR_SCHEDULE_CONFLICT,
                                  "Graveside booking conflicts on the same calendar date")


@bp.get("/cases/<case_id>/events")
@require("Admin", "Arranger", "CemeteryClerk")
def list_case_events(case_id):
    lookup.case(case_id)
    limit, offset = validate.pagination()
    items = [e for e in db.events.values() if e["case_id"] == case_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.event(e) for e in window], limit, offset, total)


@bp.get("/events/<event_id>")
@require("Admin", "Arranger", "CemeteryClerk")
def get_event(event_id):
    e = lookup.event(event_id)
    return ok_object(serialize.event(e), 200)


@bp.get("/events")
@require("Admin", "Arranger", "CemeteryClerk")
def list_events():
    limit, offset = validate.pagination()
    case_id = request.args.get("case_id")
    resource_id = request.args.get("resource_id")
    items = list(db.events.values())
    if case_id is not None:
        items = [e for e in items if e["case_id"] == case_id]
    if resource_id is not None:
        items = [e for e in items if e["resource_id"] == resource_id]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.event(e) for e in window], limit, offset, total)


@bp.post("/cases/<case_id>/events/<event_id>/cancel")
@require("Arranger")
def cancel_event(case_id, event_id):
    lookup.case(case_id)
    e = lookup.event(event_id)
    if e["case_id"] != case_id:
        raise errors.not_found("Event does not belong to this case")
    if e["status"] != "SCHEDULED":
        raise errors.invalid_state("Only a SCHEDULED event can be cancelled")
    e["status"] = "CANCELLED"
    db.touch(e)
    return ok_object(serialize.event(e), 200)
