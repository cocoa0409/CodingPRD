"""Venue and Field endpoints (PRD §3.2)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, parse_dt, touch
from errors import (ApiError, ERR_VALIDATION, ERR_VENUE_HAS_ACTIVE_MATCHES,
                    already_terminal, invalid_state, posture_forbids, raise_err)
from listing import list_response
from middleware import (forbid, get_body, req_bool, req_enum, req_int,
                        req_number, req_str, require_any_authenticated,
                        require_roles)
from response import ok

bp = Blueprint("venues", __name__, url_prefix="/api/v1")


def _own_venue_or_admin(uid, role, venue_id):
    if role == "VenueManager":
        forbid(uid != venue_id, "VenueManager may manage only their own venue.")


# ---------------------------------------------------------------------------
# Venues
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/venues")
def create_venue(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    name = req_str(data, "name")
    address = req_str(data, "address")
    rental_fee_cents = req_int(data, "rental_fee_cents", lo=0)
    revenue_share_pct = req_number(data, "revenue_share_pct", lo=0, hi=0.5)
    v = base_entity()
    v.update({
        "event_id": e["id"],
        "name": name,
        "address": address,
        "rental_fee_cents": rental_fee_cents,
        "revenue_share_pct": revenue_share_pct,
        "contract_uri": None,
        "status": "PROPOSED",
    })
    STORE.venues[v["id"]] = v
    return ok(svc.ser_venue(v), status=201)


@bp.get("/events/<id>/venues")
def list_venues(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.venues_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items.sort(key=lambda v: (v["created_at"], v["_seq"]))
    return list_response(items, svc.ser_venue)


@bp.get("/venues/<id>")
def get_venue(id):
    require_any_authenticated()
    v = svc.get_or_404(STORE.venues, id, "venue")
    return ok(svc.ser_venue(v))


@bp.post("/venues/<id>/contract")
def contract_venue(id):
    require_roles("CommissionAdmin")
    v = svc.get_or_404(STORE.venues, id, "venue")
    data = get_body()
    contract_uri = req_str(data, "contract_uri")
    e = svc.get_or_404(STORE.events, v["event_id"], "event")
    if e["posture"] not in ("BIDDING", "AWARDED", "PLANNING"):
        posture_forbids("Venue contracting requires BIDDING, AWARDED, or PLANNING posture.")
    if v["status"] == "RELEASED":
        already_terminal("venue")
    if v["status"] != "PROPOSED":
        invalid_state("Only a PROPOSED venue can be contracted.")
    v["status"] = "CONTRACTED"
    v["contract_uri"] = contract_uri
    touch(v)
    return ok(svc.ser_venue(v))


@bp.post("/venues/<id>/release")
def release_venue(id):
    require_roles("CommissionAdmin")
    v = svc.get_or_404(STORE.venues, id, "venue")
    if v["status"] == "RELEASED":
        already_terminal("venue")
    if v["status"] != "CONTRACTED":
        invalid_state("Only a CONTRACTED venue can be released.")
    field_ids = {f["id"] for f in svc.fields_of_venue(v["id"])}
    active = {"SCHEDULED", "WEATHER_DELAYED", "RESCHEDULE_QUEUE", "IN_PROGRESS"}
    for m in STORE.matches.values():
        if m["field_id"] in field_ids and m["status"] in active:
            raise_err(ERR_VENUE_HAS_ACTIVE_MATCHES,
                      "The venue hosts matches that are scheduled or in progress.")
    v["status"] = "RELEASED"
    touch(v)
    return ok(svc.ser_venue(v))


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

@bp.post("/venues/<id>/fields")
def create_field(id):
    uid, role = require_roles("CommissionAdmin", "VenueManager")
    v = svc.get_or_404(STORE.venues, id, "venue")
    _own_venue_or_admin(uid, role, v["id"])
    data = get_body()
    name = req_str(data, "name")
    surface_type = req_enum(data, "surface_type", svc.SURFACE_TYPES)
    has_lights = req_bool(data, "has_lights")
    slot_minutes = req_int(data, "slot_minutes", lo=30, hi=180)
    if v["status"] != "CONTRACTED":
        invalid_state("Fields can be created only on a CONTRACTED venue.")
    f = base_entity()
    f.update({
        "venue_id": v["id"],
        "name": name,
        "surface_type": surface_type,
        "has_lights": has_lights,
        "slot_minutes": slot_minutes,
        "status": "AVAILABLE",
        "blackout_start": None,
        "blackout_end": None,
    })
    STORE.fields[f["id"]] = f
    return ok(svc.ser_field(f), status=201)


@bp.get("/venues/<id>/fields")
def list_fields(id):
    require_any_authenticated()
    v = svc.get_or_404(STORE.venues, id, "venue")
    items = svc.fields_of_venue(v["id"])
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items.sort(key=lambda f: (f["name"], f["_seq"]))
    return list_response(items, svc.ser_field)


@bp.get("/fields/<id>")
def get_field(id):
    require_any_authenticated()
    f = svc.get_or_404(STORE.fields, id, "field")
    return ok(svc.ser_field(f))


@bp.post("/fields/<id>/blackout")
def blackout_field(id):
    uid, role = require_roles("CommissionAdmin", "VenueManager")
    f = svc.get_or_404(STORE.fields, id, "field")
    _own_venue_or_admin(uid, role, f["venue_id"])
    data = get_body()
    try:
        b_start = parse_dt(data.get("blackout_start"))
        b_end = parse_dt(data.get("blackout_end"))
    except Exception:
        raise ApiError(*ERR_VALIDATION, "blackout_start and blackout_end must be ISO 8601 datetimes.")
    req_str(data, "reason")
    v = svc.get_or_404(STORE.venues, f["venue_id"], "venue")
    if v["status"] != "CONTRACTED":
        invalid_state("The owning venue must be CONTRACTED to black out a field.")
    if f["status"] != "AVAILABLE":
        invalid_state("The field is already blacked out.")
    if b_end <= b_start:
        raise ApiError(*ERR_VALIDATION, "blackout_end must be strictly after blackout_start.")
    f["status"] = "BLACKED_OUT"
    f["blackout_start"] = b_start
    f["blackout_end"] = b_end
    touch(f)
    # Cascade: overlapping SCHEDULED matches enqueue directly for reschedule.
    for m in list(STORE.matches.values()):
        if (m["field_id"] == f["id"] and m["status"] == "SCHEDULED"
                and m["scheduled_start"] is not None and m["scheduled_end"] is not None
                and svc._overlaps(m["scheduled_start"], m["scheduled_end"], b_start, b_end)):
            svc.release_match_assignments(m, "MATCH_CANCELLED")
            m["status"] = "RESCHEDULE_QUEUE"  # original_scheduled_start preserved
            touch(m)
    return ok(svc.ser_field(f))


@bp.post("/fields/<id>/unblackout")
def unblackout_field(id):
    uid, role = require_roles("CommissionAdmin", "VenueManager")
    f = svc.get_or_404(STORE.fields, id, "field")
    _own_venue_or_admin(uid, role, f["venue_id"])
    if f["status"] != "BLACKED_OUT":
        invalid_state("The field is not blacked out.")
    f["status"] = "AVAILABLE"
    f["blackout_start"] = None
    f["blackout_end"] = None
    touch(f)
    return ok(svc.ser_field(f))


@bp.get("/fields/<id>/matches")
def list_field_matches(id):
    require_any_authenticated()
    f = svc.get_or_404(STORE.fields, id, "field")
    items = [m for m in STORE.matches.values() if m["field_id"] == f["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    # scheduled_start ASC, unscheduled last, then created_at ASC
    items.sort(key=lambda m: (m["scheduled_start"] is None,
                              m["scheduled_start"] or m["created_at"],
                              m["created_at"], m["_seq"]))
    return list_response(items, svc.ser_match)
