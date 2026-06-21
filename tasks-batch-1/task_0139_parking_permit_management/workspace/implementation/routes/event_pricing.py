"""EventPricing endpoints (create DRAFT, read, publish)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_EVENT_WINDOW_OVERLAP, ERR_INVALID_STATE
from middleware import get_json_body, require_auth
from response import ok_object
from services.common import (
    lookup,
    require_datetime,
    require_int,
    require_number,
    require_string,
)
from services.serialize import public

bp = Blueprint("event_pricing", __name__)


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


@bp.post("/parking/event-pricing")
def create_event_pricing():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    garage_id = require_string(body, "garage_id")
    name = require_string(body, "name")
    window_start_utc = require_datetime(body, "window_start_utc", required=True)
    window_end_utc = require_datetime(body, "window_end_utc", required=True)
    flat_surcharge_cents = require_int(body, "flat_surcharge_cents", required=True, minimum=0)
    multiplier = require_number(body, "multiplier", required=False, minimum=1.0, default=1.0)

    lookup(db.garages, garage_id)

    ws = db.parse_iso_dt(window_start_utc)
    we = db.parse_iso_dt(window_end_utc)
    if we <= ws:
        raise APIError(ERR_EVENT_WINDOW_OVERLAP, 409, "window_end_utc must be strictly after window_start_utc")

    ev = db.stamp_common(
        {
            "garage_id": garage_id,
            "name": name,
            "window_start_utc": window_start_utc,
            "window_end_utc": window_end_utc,
            "flat_surcharge_cents": flat_surcharge_cents,
            "multiplier": multiplier,
            "status": "DRAFT",
        }
    )
    db.event_pricing[ev["id"]] = ev
    return ok_object(public(ev), 201)


@bp.get("/parking/event-pricing/<eid>")
def read_event_pricing(eid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    ev = lookup(db.event_pricing, eid)
    return ok_object(public(ev), 200)


@bp.post("/parking/event-pricing/<eid>/publish")
def publish_event_pricing(eid):
    require_auth(["FacilityAdmin"])()
    ev = lookup(db.event_pricing, eid)
    if ev["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Only a DRAFT window may be published")

    ws = db.parse_iso_dt(ev["window_start_utc"])
    we = db.parse_iso_dt(ev["window_end_utc"])
    for other in db.event_pricing.values():
        if other["id"] == ev["id"]:
            continue
        if other["garage_id"] != ev["garage_id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        os_ = db.parse_iso_dt(other["window_start_utc"])
        oe = db.parse_iso_dt(other["window_end_utc"])
        if _overlaps(ws, we, os_, oe):
            raise APIError(
                ERR_EVENT_WINDOW_OVERLAP,
                409,
                "Window overlaps an already-PUBLISHED window for this garage",
            )

    ev["status"] = "PUBLISHED"
    db.bump(ev)
    return ok_object(public(ev), 200)
