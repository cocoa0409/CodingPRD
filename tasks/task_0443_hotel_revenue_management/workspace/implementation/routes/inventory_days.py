"""InventoryDay endpoints (PRD §3.1, §3.3)."""
from flask import Blueprint, request

from db import db, new_id
from middleware import authenticate, require_role
from response import success, list_success
from errors import (
    err, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND, ERR_DUPLICATE_INVENTORY_DAY,
    ERR_OVERSELL_LIMIT_EXCEEDED,
)
from services.common import (
    get_body, require_str, require_datetime, opt_int, opt_number,
    stay_date_midnight, iso_out, stamp_new, bump,
    parse_pagination, sort_by_created, get_or_404,
)
from services.serialize import ser_inventory_day
from services.calc import (
    recompute_availability, ceiling_for_inv, pickup_forecast,
)

bp = Blueprint("inventory_days", __name__)

ALL_ROLES = {"RevenueManager", "GroupSalesManager", "ChannelManager", "Analyst"}
FORECAST_METHODS = {"SNAPSHOT_PACE", "TRAILING_PICKUP"}


@bp.route("/inventory-days", methods=["POST"])
def create_inventory_day():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = get_body()
    room_type_id = require_str(body, "room_type_id")
    stay_dt = require_datetime(body, "stay_date")
    stay_mid = stay_date_midnight(stay_dt)
    stay_key = stay_mid.strftime("%Y-%m-%d")

    # physical_capacity defaults to room type physical_rooms when omitted.
    rt = db.room_types.get(room_type_id)
    if rt is None:
        raise err(ERR_FK_NOT_FOUND, "room_type_id does not reference an existing room type")

    physical_capacity = opt_int(body, "physical_capacity", rt["physical_rooms"])
    if physical_capacity < 0:
        raise err(ERR_INVALID_REQUEST, "physical_capacity must be >= 0")
    transient_sold = opt_int(body, "transient_sold_rooms", 0)
    if transient_sold < 0:
        raise err(ERR_INVALID_REQUEST, "transient_sold_rooms must be >= 0")
    transient_rev = opt_number(body, "transient_revenue", 0)
    if transient_rev < 0:
        raise err(ERR_INVALID_REQUEST, "transient_revenue must be >= 0")

    # At most one InventoryDay per (room_type_id, stay_date).
    for inv in db.inventory_days.values():
        if inv["room_type_id"] == room_type_id and inv["stay_date_key"] == stay_key:
            raise err(ERR_DUPLICATE_INVENTORY_DAY, "InventoryDay already exists for this night")

    rec = {
        "id": new_id(),
        "room_type_id": room_type_id,
        "stay_date": iso_out(stay_mid),
        "stay_date_key": stay_key,
        "physical_capacity": physical_capacity,
        "group_held_rooms": 0,
        "transient_sold_rooms": transient_sold,
        "transient_revenue": transient_rev,
        "rooms_sold": 0,
        "rooms_available": 0,
        "_seq": db.next_seq(),
    }
    stamp_new(rec)
    db.inventory_days[rec["id"]] = rec
    recompute_availability(rec)
    return success(ser_inventory_day(rec), status=201)


@bp.route("/inventory-days/<iid>", methods=["GET"])
def get_inventory_day(iid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.inventory_days, iid)
    recompute_availability(rec)
    return success(ser_inventory_day(rec), status=200)


@bp.route("/inventory-days", methods=["GET"])
def list_inventory_days():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    room_type_id = request.args.get("room_type_id")
    stay_date = request.args.get("stay_date")
    stay_key = None
    if stay_date:
        from services.common import parse_iso
        stay_key = stay_date_midnight(parse_iso(stay_date, "stay_date")).strftime("%Y-%m-%d")
    items = []
    for inv in db.inventory_days.values():
        if room_type_id is not None and inv["room_type_id"] != room_type_id:
            continue
        if stay_key is not None and inv["stay_date_key"] != stay_key:
            continue
        items.append(inv)
    items = sort_by_created(items)
    total = len(items)
    page = [ser_inventory_day(inv) for inv in items[offset:offset + limit]]
    return list_success(page, limit, offset, total)


@bp.route("/inventory-days/<iid>", methods=["PATCH"])
def patch_inventory_day(iid):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    rec = get_or_404(db.inventory_days, iid)
    body = get_body()

    new_cap = rec["physical_capacity"]
    if "physical_capacity" in body and body["physical_capacity"] is not None:
        new_cap = opt_int(body, "physical_capacity", new_cap)
        if new_cap < 0:
            raise err(ERR_INVALID_REQUEST, "physical_capacity must be >= 0")
    new_sold = rec["transient_sold_rooms"]
    if "transient_sold_rooms" in body and body["transient_sold_rooms"] is not None:
        new_sold = opt_int(body, "transient_sold_rooms", new_sold)
        if new_sold < 0:
            raise err(ERR_INVALID_REQUEST, "transient_sold_rooms must be >= 0")
    new_rev = rec["transient_revenue"]
    if "transient_revenue" in body and body["transient_revenue"] is not None:
        new_rev = opt_number(body, "transient_revenue", new_rev)
        if new_rev < 0:
            raise err(ERR_INVALID_REQUEST, "transient_revenue must be >= 0")

    # Oversell ceiling check: rooms_sold (new transient + current group held) must
    # not exceed the night's oversell ceiling.
    held = rec["group_held_rooms"]
    # Recompute held against committed blocks to be safe.
    recompute_availability(rec)
    held = rec["group_held_rooms"]
    prospective_sold = new_sold + held
    prop = _property_for(rec)
    ob = prop["overbooking_limit_pct"] if prop else 0.0
    from services.calc import oversell_ceiling
    ceiling = oversell_ceiling(new_cap, ob)
    if prospective_sold > ceiling:
        raise err(ERR_OVERSELL_LIMIT_EXCEEDED, "Update would exceed the night's oversell ceiling")

    rec["physical_capacity"] = new_cap
    rec["transient_sold_rooms"] = new_sold
    rec["transient_revenue"] = new_rev
    recompute_availability(rec)
    bump(rec)
    return success(ser_inventory_day(rec), status=200)


@bp.route("/inventory-days/<iid>/forecast", methods=["GET"])
def forecast_inventory_day(iid):
    _, role = authenticate()
    require_role(role, {"RevenueManager", "Analyst"})
    rec = get_or_404(db.inventory_days, iid)
    method = request.args.get("method", "SNAPSHOT_PACE")
    if method not in FORECAST_METHODS:
        raise err(ERR_INVALID_REQUEST, "method must be SNAPSHOT_PACE or TRAILING_PICKUP")
    recompute_availability(rec)
    final, occ = pickup_forecast(rec, method)
    data = {
        "forecast_final_sold": final,
        "forecast_occupancy_pct": occ,
        "method": method,
    }
    return success(data, status=200)


def _property_for(inv):
    rt = db.room_types.get(inv["room_type_id"])
    if rt is None:
        return None
    return db.properties.get(rt["property_id"])
