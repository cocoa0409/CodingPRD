"""Artists, BookingAgents, Shows, and the house clock."""

from datetime import timedelta
from datetime import datetime, timezone

from flask import Blueprint, g, request

import store
from domain import DEPOSIT_LEAD_DAYS
from envelope import created, ok
from errors import biz, invalid_request, not_found
from helpers import (body, filter_eq, get_show, list_response, lookup,
                     parse_date, req_date, req_dt, req_enum, req_int, req_num,
                     req_str, require_roles, ser_agent, ser_artist, ser_show)

bp = Blueprint("roster", __name__)

ALL_READ = ("VenueManager", "BookingAgent", "Promoter", "Accountant", "ProductionManager")


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------
@bp.post("/artists")
def create_artist():
    require_roles("VenueManager")
    b = body()
    legal_name = req_str(b, "legal_name")
    agency = req_str(b, "agency")
    floor = req_int(b, "guarantee_floor_cents", minimum=0)
    deposit_pct = req_num(b, "deposit_pct")
    if not (0.0 <= deposit_pct <= 0.5):
        raise invalid_request("deposit_pct must be between 0.0 and 0.5 inclusive")
    a = store.new_common({
        "legal_name": legal_name,
        "agency": agency,
        "guarantee_floor_cents": floor,
        "deposit_pct": deposit_pct,
        "status": "ACTIVE",
    })
    store.artists[a["id"]] = a
    return created(ser_artist(a))


@bp.get("/artists/<aid>")
def get_artist(aid):
    require_roles(*ALL_READ)
    return ok(ser_artist(lookup(store.artists, aid, "Artist")))


@bp.get("/artists")
def list_artists():
    require_roles(*ALL_READ)
    return list_response(list(store.artists.values()), ser_artist)


# ---------------------------------------------------------------------------
# Booking agents
# ---------------------------------------------------------------------------
@bp.post("/booking-agents")
def create_agent():
    require_roles("VenueManager")
    b = body()
    a = store.new_common({
        "display_name": req_str(b, "display_name"),
        "agency_name": req_str(b, "agency_name"),
        "status": "ACTIVE",
    })
    store.booking_agents[a["id"]] = a
    return created(ser_agent(a))


@bp.get("/booking-agents/<aid>")
def get_agent(aid):
    require_roles("VenueManager", "BookingAgent", "Promoter")
    return ok(ser_agent(lookup(store.booking_agents, aid, "BookingAgent")))


# ---------------------------------------------------------------------------
# Shows
# ---------------------------------------------------------------------------
def _validate_show_schedule(show_date, doors, curfew):
    today = store.now().date()
    if show_date < today + timedelta(days=7):
        raise biz("ERR_INVALID_SHOW_SCHEDULE",
                  "show_date must fall at least seven days after the current date")
    if curfew <= doors:
        raise biz("ERR_INVALID_SHOW_SCHEDULE", "curfew_at_utc must be strictly later than doors_at_utc")
    if doors.date() != show_date:
        raise biz("ERR_INVALID_SHOW_SCHEDULE", "doors_at_utc must fall on show_date")


def _create_show(artist_id, room, show_date, doors, curfew, total_capacity, on_sale):
    s = store.new_common({
        "artist_id": artist_id,
        "room": room,
        "show_date": show_date.isoformat(),
        "_show_date_obj": show_date,
        "doors_at_utc": doors,
        "curfew_at_utc": curfew,
        "status": "HOLD_PENDING",
        "hold_priority": "NONE",
        "deal_id": None,
        "deposit_required_cents": 0,
        "deposit_paid_cents": 0,
        "deposit_due_by_utc": None,
        "total_capacity": total_capacity,
        "tickets_sold": 0,
        "gross_ticket_revenue_cents": 0,
        "on_sale_at_utc": on_sale,
        "weather_or_emergency_flag": False,
        "cancellation_reason": "NONE",
    })
    store.shows[s["id"]] = s
    cl = store.new_common({
        "show_id": s["id"],
        "hospitality_done": False,
        "tech_done": False,
        "backline_done": False,
        "production_requirements_done": False,
        "insurance_cert_received": False,
        "w9_received": False,
        "all_complete": False,
    })
    store.advance_checklists[cl["id"]] = cl
    s["_checklist_id"] = cl["id"]
    return s


@bp.post("/shows")
def create_show():
    require_roles("BookingAgent", "VenueManager")
    b = body()
    artist_id = req_str(b, "artist_id")
    room = req_enum(b, "room", ("MAIN_ROOM", "LOUNGE"))
    show_date = req_date(b, "show_date")
    doors = req_dt(b, "doors_at_utc")
    curfew = req_dt(b, "curfew_at_utc")
    total_capacity = req_int(b, "total_capacity", minimum=1)
    on_sale = req_dt(b, "on_sale_at_utc")
    # Body-referenced FK existence (pipeline step 4)
    lookup(store.artists, artist_id, "Artist")
    # Business: booking lead time + schedule sanity (rule 11)
    _validate_show_schedule(show_date, doors, curfew)
    s = _create_show(artist_id, room, show_date, doors, curfew, total_capacity, on_sale)
    return created(ser_show(s))


@bp.get("/shows/<sid>")
def get_show_route(sid):
    require_roles(*ALL_READ)
    return ok(ser_show(get_show(sid)))


@bp.get("/shows")
def list_shows():
    require_roles(*ALL_READ)
    items = list(store.shows.values())
    items = filter_eq(items, "status", request.args.get("status"))
    items = filter_eq(items, "artist_id", request.args.get("artist_id"))
    items = filter_eq(items, "room", request.args.get("room"))
    items = filter_eq(items, "show_date", request.args.get("show_date"))
    items = filter_eq(items, "deal_id", request.args.get("deal_id"))
    return list_response(items, ser_show)


# ---------------------------------------------------------------------------
# House clock (PRD 2.7)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("VenueManager")
    b = body()
    target = req_dt(b, "to_iso8601")
    store.set_clock(target)
    store.sweep_time_transitions()
    return ok({"current_utc": store.fmt_dt(store.now())})
