"""Special event production and displacement (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint

import serialize
from auth import ROLE_BOX, ROLE_EXEC, ROLE_PROGRAMMER, authorize
from calc import compute_block, venue_local_day
from cascade import Ledger, cancel_showtime
from errors import ApiError
from response import object_response, paged
from store import new_record, ordered, touch
from timeutil import local_day_start_instant
from validate import (EVENT_TYPES, body, find, insert, must_find, opt_int, query_str,
                      req_bool, req_enum, req_int, req_str, rows)

bp = Blueprint("events", __name__)

EVENT_READ = (ROLE_PROGRAMMER, ROLE_BOX, ROLE_EXEC)


def require_event_state(event, allowed):
    if event["status"] not in allowed:
        raise ApiError("ERR_SPECIAL_EVENT_INVALID_STATE",
                       "An event in %s does not admit this transition." % event["status"])


def _recompute_block(showtime, venue, title):
    end_at, blocked_until = compute_block(venue, title, showtime["start_at"],
                                          showtime["extra_minutes"])
    showtime["end_at"] = end_at
    showtime["blocked_until"] = blocked_until


@bp.post("/special-events")
def create_event():
    authorize((ROLE_PROGRAMMER,))
    payload = body()
    event_type = req_enum(payload, "event_type", EVENT_TYPES)
    guest_name = req_str(payload, "guest_name")
    extra_minutes = req_int(payload, "extra_minutes", minimum=0)
    surcharge_cents = req_int(payload, "surcharge_cents", minimum=0)
    guest_fee_cents = req_int(payload, "guest_fee_cents", minimum=0)
    showtime_id = req_str(payload, "showtime_id")
    showtime = must_find("showtimes", showtime_id)
    if showtime["status"] != "SCHEDULED":
        raise ApiError("ERR_SHOWTIME_INVALID_STATE",
                       "An event may only wrap a scheduled screening.")
    for other in rows("events"):
        if other["showtime_id"] == showtime_id and other["status"] in ("PLANNED", "CONFIRMED"):
            raise ApiError("ERR_SPECIAL_EVENT_INVALID_STATE",
                           "This screening already carries a live special event.")
    row = new_record(
        showtime_id=showtime_id,
        event_type=event_type,
        guest_name=guest_name,
        extra_minutes=extra_minutes,
        surcharge_cents=surcharge_cents,
        guest_fee_cents=guest_fee_cents,
        status="PLANNED",
        displaced_showtime_ids=[],
        cancel_reason=None,
    )
    insert("events", row)
    return object_response(serialize.event(row), 201)


@bp.get("/special-events/<event_id>")
def read_event(event_id):
    authorize(EVENT_READ)
    return object_response(serialize.event(must_find("events", event_id)))


@bp.get("/special-events")
def list_events():
    authorize(EVENT_READ)
    found = rows("events")
    for name in ("showtime_id", "status", "event_type"):
        value = query_str(name)
        if value is not None:
            found = [e for e in found if e[name] == value]
    return paged(ordered(found), serialize.event)


@bp.post("/special-events/<event_id>/confirm")
def confirm_event(event_id):
    authorize((ROLE_EXEC,))
    payload = body()
    displace_conflicts = req_bool(payload, "displace_conflicts")
    event = must_find("events", event_id)
    require_event_state(event, ("PLANNED",))
    showtime = must_find("showtimes", event["showtime_id"])
    if showtime["status"] != "SCHEDULED":
        raise ApiError("ERR_SPECIAL_EVENT_INVALID_STATE",
                       "The wrapped screening is no longer scheduled.")
    venue = must_find("venues", showtime["venue_id"])
    title = must_find("titles", showtime["title_id"])
    end_at, blocked_until = compute_block(venue, title, showtime["start_at"],
                                          event["extra_minutes"])
    conflicts = [other for other in ordered(rows("showtimes"))
                 if other["id"] != showtime["id"]
                 and other["venue_id"] == venue["id"]
                 and other["status"] != "CANCELLED"
                 and showtime["start_at"] < other["blocked_until"]
                 and other["start_at"] < blocked_until]
    if not displace_conflicts and conflicts:
        raise ApiError("ERR_SCREEN_SLOT_CONFLICT",
                       "The enlarged block collides with another screening.")
    day_start = local_day_start_instant(venue_local_day(venue, showtime["start_at"]),
                                        venue["utc_offset_minutes"])
    if blocked_until > day_start + timedelta(days=1):
        raise ApiError("ERR_SHOWTIME_WINDOW_INVALID",
                       "The enlarged block would leave the auditorium's operating day.")
    ledger = Ledger()
    # Hop one: the event is confirmed and the screening's block grows.
    event["status"] = "CONFIRMED"
    showtime["extra_minutes"] = event["extra_minutes"]
    showtime["surcharge_cents"] = event["surcharge_cents"]
    showtime["end_at"] = end_at
    showtime["blocked_until"] = blocked_until
    ledger.mark(showtime)
    # Hops two through four: displaced screenings collapse with their sales.
    for other in conflicts:
        if other["status"] != "SCHEDULED":
            continue
        cancel_showtime(other, "DISPLACED_BY_SPECIAL_EVENT", ledger)
        event["displaced_showtime_ids"].append(other["id"])
    ledger.mark(event)
    ledger.flush()
    return object_response(serialize.event(event))


@bp.post("/special-events/<event_id>/cancel")
def cancel_event(event_id):
    authorize((ROLE_PROGRAMMER, ROLE_EXEC))
    payload = body()
    cancel_reason = req_str(payload, "cancel_reason")
    event = must_find("events", event_id)
    require_event_state(event, ("PLANNED", "CONFIRMED"))
    was_confirmed = event["status"] == "CONFIRMED"
    ledger = Ledger()
    event["status"] = "CANCELLED"
    event["cancel_reason"] = cancel_reason
    ledger.mark(event)
    if was_confirmed:
        showtime = find("showtimes", event["showtime_id"])
        if showtime is not None:
            venue = find("venues", showtime["venue_id"])
            title = find("titles", showtime["title_id"])
            showtime["extra_minutes"] = 0
            showtime["surcharge_cents"] = 0
            if venue is not None and title is not None:
                _recompute_block(showtime, venue, title)
            ledger.mark(showtime)
    ledger.flush()
    return object_response(serialize.event(event))
