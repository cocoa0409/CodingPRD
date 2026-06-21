"""Storage-zone and booking endpoints (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth
from response import ok_object, ok_array
from services.common import (
    get_json_body, require_fields, require_str, require_number,
    parse_pagination, created_sort_key, paginate, parse_dt, round_qty,
)
from services.entities import (
    base_fields, get_facility_or_404, get_zone_or_404, get_booking_or_404,
)
from services.serialize import public
from services.storage import peak_load_exceeds

bp = Blueprint("storage", __name__)

ALL_ROLES = ["QualityManager", "ReceivingClerk", "ProductionOperator", "SafetyAuditor"]


@bp.post("/traceability/zones")
def create_zone():
    require_auth(["QualityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "zone_code", "capacity_units", "target_temp_c"])
    facility_id = require_str(body, "facility_id")
    zone_code = require_str(body, "zone_code")
    capacity_units = require_number(body, "capacity_units", positive=True)
    target_temp_c = require_number(body, "target_temp_c")

    get_facility_or_404(facility_id)

    # zone_code unique per facility_id (scaffold §1.1) -> body constraint.
    for z in db.zones.values():
        if z["facility_id"] == facility_id and z["zone_code"] == zone_code:
            raise err("ERR_INVALID_REQUEST", "zone_code must be unique per facility")

    rec = base_fields(common=True)
    rec.update({
        "facility_id": facility_id,
        "zone_code": zone_code,
        "capacity_units": capacity_units,
        "target_temp_c": target_temp_c,
    })
    db.zones[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/traceability/zones/<zid>")
def get_zone(zid):
    require_auth(ALL_ROLES)
    rec = get_zone_or_404(zid)
    return ok_object(public(rec), 200)


@bp.post("/traceability/zones/<zid>/bookings")
def create_booking(zid):
    require_auth(["QualityManager", "ReceivingClerk"])
    zone = get_zone_or_404(zid)
    body = get_json_body()
    require_fields(body, ["lot_id", "start_utc", "end_utc", "capacity_units"])
    lot_id = require_str(body, "lot_id")
    require_str(body, "start_utc")
    require_str(body, "end_utc")
    capacity_units = require_number(body, "capacity_units", positive=True)

    # FK resolution + same-facility ownership (priority 5).
    lot = db.lots.get(lot_id)
    if lot is None:
        raise err("ERR_LOT_NOT_FOUND", "Lot not found")
    if lot["facility_id"] != zone["facility_id"]:
        raise err("ERR_CROSS_FACILITY_REFERENCE", "Lot and zone belong to different facilities")

    start_dt = parse_dt(body["start_utc"], "start_utc")
    end_dt = parse_dt(body["end_utc"], "end_utc")

    # priority 16: interval validity (end strictly > start).
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_INTERVAL", "end_utc must be strictly greater than start_utc")

    # priority 17: peak coincident capacity.
    if peak_load_exceeds(zid, start_dt, end_dt, capacity_units, zone["capacity_units"]):
        raise err("ERR_ZONE_CAPACITY_EXCEEDED", "Peak overlapping capacity exceeds zone capacity")

    from services.common import fmt_dt
    rec = base_fields(common=True)
    rec.update({
        "zone_id": zid,
        "lot_id": lot_id,
        "start_utc": fmt_dt(start_dt),
        "end_utc": fmt_dt(end_dt),
        "capacity_units": round_qty(capacity_units),
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.bookings[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/traceability/bookings/<bid>")
def get_booking(bid):
    require_auth(ALL_ROLES)
    rec = get_booking_or_404(bid)
    return ok_object(public(rec), 200)


@bp.get("/traceability/bookings")
def list_bookings():
    require_auth(ALL_ROLES)
    items = list(db.bookings.values())
    zone_id = request.args.get("zone_id")
    lot_id = request.args.get("lot_id")
    if zone_id is not None:
        items = [x for x in items if x["zone_id"] == zone_id]
    if lot_id is not None:
        items = [x for x in items if x["lot_id"] == lot_id]
    items.sort(key=created_sort_key)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return ok_array([public(x) for x in page], limit, offset, total, 200)
