"""Fitting rooms and fitting-room holds (PRD §3.3)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, validate_interval,
    parse_pagination, paginate, serialize, serialize_list, recompute_variant,
)

bp = Blueprint("fitting_rooms", __name__)

NON_TERMINAL_HOLD = ("ACTIVE", "EXTENDED")


def _intervals_overlap(s1, e1, s2, e2):
    """Half-open [start,end): back-to-back (e1==s2 or e2==s1) does not overlap."""
    return s1 < e2 and s2 < e1


def _check_room_overlap(room_id, start_minute, end_minute, exclude_hold_id=None):
    for h in db.fitting_room_holds.values():
        if h["fitting_room_id"] != room_id:
            continue
        if exclude_hold_id is not None and h["id"] == exclude_hold_id:
            continue
        if h["status"] not in NON_TERMINAL_HOLD:
            continue
        if _intervals_overlap(start_minute, end_minute, h["start_minute"], h["end_minute"]):
            raise err(errors.ERR_ROOM_DOUBLE_BOOKED, "interval overlaps another hold on this room")


# --- Fitting rooms ---

@bp.post("/fitting-rooms")
def create_room():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate"})
    body = get_json_body()
    boutique_id = require_str(body, "boutique_id")
    label = require_str(body, "label")
    get_or_404("boutique", boutique_id)
    rec = stamp_new({
        "boutique_id": boutique_id,
        "label": label,
        "status": "OPEN",
    })
    db.fitting_rooms[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/fitting-rooms/<rid>")
def get_room(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("fitting_room", rid)
    return success(serialize(rec))


@bp.get("/fitting-rooms")
def list_rooms():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.fitting_rooms.values())
    boutique_id = request.args.get("boutique_id")
    if boutique_id is not None:
        items = [r for r in items if r["boutique_id"] == boutique_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


# --- Holds ---

@bp.post("/fitting-room-holds")
def create_hold():
    user_id, role = authenticate()
    require_role(role, {"StoreAssociate", "Customer"})
    body = get_json_body()

    # Existence (priority 3), left-to-right.
    fitting_room_id = require_str(body, "fitting_room_id")
    customer_id = require_str(body, "customer_id")
    sku_variant_id = require_str(body, "sku_variant_id")
    room = get_or_404("fitting_room", fitting_room_id)
    customer = get_or_404("customer", customer_id)
    variant = get_or_404("sku_variant", sku_variant_id)

    # Ownership (priority 4) before body well-formedness.
    if role == "Customer" and user_id != customer["id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")

    # Body well-formedness (priority 5).
    start_minute = require_int(body, "start_minute")
    end_minute = require_int(body, "end_minute")
    validate_interval(start_minute, end_minute)

    # Business check 1: room overlap (half-open).
    _check_room_overlap(fitting_room_id, start_minute, end_minute)

    # Business check 2: variant reservable.
    if variant["status"] != "STOCKED" or variant["available"] < 1:
        raise err(errors.ERR_INSUFFICIENT_INVENTORY, "variant not reservable")

    boutique = db.boutiques[room["boutique_id"]]
    style = db.styles[variant["style_id"]]
    rec = stamp_new({
        "fitting_room_id": fitting_room_id,
        "customer_id": customer_id,
        "sku_variant_id": sku_variant_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "status": "ACTIVE",
        "held_price_cents": style["current_price_cents"],
        "sales_order_id": None,
        "_business_date": boutique["current_business_date"],
    })
    db.fitting_room_holds[rec["id"]] = rec

    variant["reserved"] += 1
    recompute_variant(variant)
    return success(serialize(rec), 201)


@bp.get("/fitting-room-holds/<rid>")
def get_hold(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("fitting_room_hold", rid)
    return success(serialize(rec))


@bp.get("/fitting-rooms/<rid>/holds")
def list_room_holds(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    get_or_404("fitting_room", rid)
    limit, offset = parse_pagination()
    items = [h for h in db.fitting_room_holds.values() if h["fitting_room_id"] == rid]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.get("/fitting-room-holds")
def list_holds():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.fitting_room_holds.values())
    customer_id = request.args.get("customer_id")
    sku_variant_id = request.args.get("sku_variant_id")
    sales_order_id = request.args.get("sales_order_id")
    if customer_id is not None:
        items = [h for h in items if h["customer_id"] == customer_id]
    if sku_variant_id is not None:
        items = [h for h in items if h["sku_variant_id"] == sku_variant_id]
    if sales_order_id is not None:
        items = [h for h in items if h["sales_order_id"] == sales_order_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/fitting-room-holds/<rid>/extend")
def extend_hold(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreAssociate", "Customer"})
    hold = get_or_404("fitting_room_hold", rid)
    if role == "Customer" and user_id != hold["customer_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    body = get_json_body()
    end_minute = require_int(body, "end_minute")
    # State check (priority 6): extend is defined only from ACTIVE.
    if hold["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "extend requires ACTIVE")
    # end_minute must remain a valid interval against the existing start.
    validate_interval(hold["start_minute"], end_minute)
    # Re-check room overlap (excluding self).
    _check_room_overlap(hold["fitting_room_id"], hold["start_minute"], end_minute, exclude_hold_id=hold["id"])
    hold["end_minute"] = end_minute
    hold["status"] = "EXTENDED"
    touch(hold)
    return success(serialize(hold))


@bp.post("/fitting-room-holds/<rid>/convert")
def convert_hold(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    hold = get_or_404("fitting_room_hold", rid)
    body = get_json_body()
    sales_order_id = require_str(body, "sales_order_id")
    order = get_or_404("sales_order", sales_order_id)
    # State check (priority 6).
    if hold["status"] not in ("ACTIVE", "EXTENDED"):
        raise err(errors.ERR_INVALID_STATE, "convert requires ACTIVE or EXTENDED")
    # The order must already contain a line for this hold's sku_variant_id.
    has_line = any(
        l["sales_order_id"] == sales_order_id and l["sku_variant_id"] == hold["sku_variant_id"]
        for l in db.order_lines.values()
    )
    if not has_line:
        raise err(errors.ERR_INVALID_STATE, "sales order has no line for this hold's variant")

    hold["status"] = "CONVERTED"
    hold["sales_order_id"] = sales_order_id
    touch(hold)
    variant = db.sku_variants.get(hold["sku_variant_id"])
    if variant is not None:
        variant["reserved"] = max(0, variant["reserved"] - 1)
        recompute_variant(variant)
    return success(serialize(hold))


@bp.post("/fitting-room-holds/<rid>/release")
def release_hold(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreAssociate", "Customer"})
    hold = get_or_404("fitting_room_hold", rid)
    if role == "Customer" and user_id != hold["customer_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    if hold["status"] not in ("ACTIVE", "EXTENDED"):
        raise err(errors.ERR_INVALID_STATE, "release requires ACTIVE or EXTENDED")
    hold["status"] = "RELEASED"
    touch(hold)
    variant = db.sku_variants.get(hold["sku_variant_id"])
    if variant is not None:
        variant["reserved"] = max(0, variant["reserved"] - 1)
        recompute_variant(variant)
    return success(serialize(hold))
