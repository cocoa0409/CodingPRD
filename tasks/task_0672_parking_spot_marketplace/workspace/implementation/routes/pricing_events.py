"""Pricing event (surge) creation, reads, and cancellation."""
from flask import Blueprint, request

from db import db, make_versioned, touch
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_EVENT_ZONE_CONFLICT,
)
from middleware import require_auth, require_role
from response import success, success_list
from serialize import pricing_event_view
from util import require_body, require_str, require_int, require_datetime, parse_pagination, paginate

bp = Blueprint("pricing_events", __name__)

EVENT_BUFFER_S = 3600


@bp.post("/pricing-events")
def create_pricing_event():
    caller = require_auth()
    require_role(caller, "PlatformAdmin")
    data = require_body(request.get_json(silent=True))
    zone_code = require_str(data, "zone_code")
    window_start = require_datetime(data, "window_start")
    window_end = require_datetime(data, "window_end")
    surge_multiplier_bps = require_int(data, "surge_multiplier_bps")
    if surge_multiplier_bps < 10000 or surge_multiplier_bps > 50000:
        raise err(ERR_INVALID_REQUEST, "surge_multiplier_bps must be within 10000..50000.")

    # Zone buffer conflict: reject when new.start < other.end+buffer AND new.end+buffer > other.start
    new_start = window_start.timestamp()
    new_end = window_end.timestamp()
    for ev in db.pricing_events.values():
        if ev["zone_code"] != zone_code or ev["status"] != "ACTIVE":
            continue
        other_start = ev["_window_start_dt"].timestamp()
        other_end = ev["_window_end_dt"].timestamp()
        if new_start < (other_end + EVENT_BUFFER_S) and (new_end + EVENT_BUFFER_S) > other_start:
            raise err(ERR_EVENT_ZONE_CONFLICT, "Pricing event too close to an active event in zone.")

    rec = make_versioned(
        {
            "zone_code": zone_code,
            "window_start": data["window_start"],
            "window_end": data["window_end"],
            "surge_multiplier_bps": surge_multiplier_bps,
            "status": "ACTIVE",
            "_window_start_dt": window_start,
            "_window_end_dt": window_end,
        }
    )
    db.pricing_events[rec["id"]] = rec
    return success(pricing_event_view(rec), status=201)


@bp.get("/pricing-events/<event_id>")
def get_pricing_event(event_id):
    caller = require_auth()
    require_role(caller, "PlatformAdmin", "Host", "Driver")
    rec = db.pricing_events.get(event_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Pricing event not found.")
    return success(pricing_event_view(rec))


@bp.get("/pricing-events")
def list_pricing_events():
    caller = require_auth()
    require_role(caller, "PlatformAdmin", "Host", "Driver")
    limit, offset = parse_pagination(request.args)
    zone_code = request.args.get("zone_code")
    items = list(db.pricing_events.values())
    if zone_code is not None:
        items = [e for e in items if e["zone_code"] == zone_code]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([pricing_event_view(e) for e in page], limit, offset, total)


@bp.post("/pricing-events/<event_id>/cancel")
def cancel_pricing_event(event_id):
    caller = require_auth()
    require_role(caller, "PlatformAdmin")
    rec = db.pricing_events.get(event_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Pricing event not found.")
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Pricing event is not ACTIVE.")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(pricing_event_view(rec))
