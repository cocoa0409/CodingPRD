"""Spot listing and availability management."""
from flask import Blueprint, request

from db import db, make_versioned, touch
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE,
)
from middleware import require_auth, require_role
from response import success, success_list
from serialize import spot_view, booking_view
from util import (
    require_body,
    require_str,
    require_int,
    optional_int,
    require_datetime,
    parse_pagination,
    paginate,
)

bp = Blueprint("spots", __name__)


@bp.post("/spots")
def create_spot():
    caller = require_auth()
    require_role(caller, "Host")
    data = require_body(request.get_json(silent=True))
    host_id = require_str(data, "host_id")
    title = require_str(data, "title")
    zone_code = require_str(data, "zone_code")
    base_hourly_cents = require_int(data, "base_hourly_cents")
    base_daily_cents = require_int(data, "base_daily_cents")
    monthly_flat_cents = require_int(data, "monthly_flat_cents")
    availability_start = require_datetime(data, "availability_start")
    availability_end = require_datetime(data, "availability_end")
    overstay_grace_minutes = optional_int(data, "overstay_grace_minutes", 15)

    if base_hourly_cents < 100:
        raise err(ERR_INVALID_REQUEST, "base_hourly_cents must be >= 100.")
    if base_daily_cents < 500:
        raise err(ERR_INVALID_REQUEST, "base_daily_cents must be >= 500.")
    if monthly_flat_cents < 5000:
        raise err(ERR_INVALID_REQUEST, "monthly_flat_cents must be >= 5000.")
    if overstay_grace_minutes < 0 or overstay_grace_minutes > 120:
        raise err(ERR_INVALID_REQUEST, "overstay_grace_minutes must be within 0..120.")

    # Existence of referenced resources (§2.10) is checked before ownership.
    if host_id not in db.hosts:
        raise err(ERR_NOT_FOUND, "Host not found.")
    # The acting Host must own the spot being created (host_id == X-User-ID).
    if host_id != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "host_id must match the acting host.")

    rec = make_versioned(
        {
            "host_id": host_id,
            "title": title,
            "zone_code": zone_code,
            "base_hourly_cents": base_hourly_cents,
            "base_daily_cents": base_daily_cents,
            "monthly_flat_cents": monthly_flat_cents,
            "availability_start": data["availability_start"],
            "availability_end": data["availability_end"],
            "overstay_grace_minutes": overstay_grace_minutes,
            "listing_status": "LISTED",
            "_availability_start_dt": availability_start,
            "_availability_end_dt": availability_end,
        }
    )
    db.spots[rec["id"]] = rec
    return success(spot_view(rec), status=201)


@bp.get("/spots/<spot_id>")
def get_spot(spot_id):
    caller = require_auth()
    require_role(caller, "Host", "Driver", "PlatformAdmin")
    rec = db.spots.get(spot_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Spot not found.")
    return success(spot_view(rec))


@bp.get("/spots")
def list_spots():
    caller = require_auth()
    require_role(caller, "Host", "Driver", "PlatformAdmin")
    limit, offset = parse_pagination(request.args)
    host_id = request.args.get("host_id")
    zone_code = request.args.get("zone_code")
    items = list(db.spots.values())
    if host_id is not None:
        items = [s for s in items if s["host_id"] == host_id]
    if zone_code is not None:
        items = [s for s in items if s["zone_code"] == zone_code]
    items.sort(key=lambda s: s["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([spot_view(s) for s in page], limit, offset, total)


@bp.get("/spots/<spot_id>/bookings")
def list_spot_bookings(spot_id):
    caller = require_auth()
    require_role(caller, "Host", "PlatformAdmin")
    spot = db.spots.get(spot_id)
    if spot is None:
        raise err(ERR_NOT_FOUND, "Spot not found.")
    limit, offset = parse_pagination(request.args)
    items = [b for b in db.bookings.values() if b["spot_id"] == spot_id]
    items.sort(key=lambda b: b["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([booking_view(b) for b in page], limit, offset, total)


@bp.post("/spots/<spot_id>/unlist")
def unlist_spot(spot_id):
    caller = require_auth()
    require_role(caller, "Host")
    spot = db.spots.get(spot_id)
    if spot is None:
        raise err(ERR_NOT_FOUND, "Spot not found.")
    # Ownership before state.
    if spot["host_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Host does not own this spot.")
    if spot["listing_status"] != "LISTED":
        raise err(ERR_INVALID_STATE, "Spot is not LISTED.")
    # No booking on this spot in RESERVED or CHECKED_IN.
    for b in db.bookings.values():
        if b["spot_id"] == spot_id and b["occupancy_status"] in ("RESERVED", "CHECKED_IN"):
            raise err(ERR_INVALID_STATE, "Spot has an active booking.")
    spot["listing_status"] = "UNLISTED"
    touch(spot)
    return success(spot_view(spot))


@bp.post("/spots/<spot_id>/relist")
def relist_spot(spot_id):
    caller = require_auth()
    require_role(caller, "Host")
    spot = db.spots.get(spot_id)
    if spot is None:
        raise err(ERR_NOT_FOUND, "Spot not found.")
    if spot["host_id"] != caller.user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Host does not own this spot.")
    if spot["listing_status"] != "UNLISTED":
        raise err(ERR_INVALID_STATE, "Spot is not UNLISTED.")
    spot["listing_status"] = "LISTED"
    touch(spot)
    return success(spot_view(spot))
