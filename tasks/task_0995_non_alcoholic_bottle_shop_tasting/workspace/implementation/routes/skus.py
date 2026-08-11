"""SKU and InventoryLot endpoints."""
from flask import Blueprint, request

import db as _db
from db import db, new_entity, touch
from errors import duplicate, invalid_request, not_found
from helpers import (body, get_or_404, opt_bool, opt_int, opt_str, paginate,
                     pagination_params, parse_bool_param, public, req_date,
                     req_int, req_str)
from middleware import require
from response import success
from services import (compute_age_neutral_class, recompute_lot_status,
                      recompute_on_hand)

bp = Blueprint("skus", __name__)

READ_ROLES = ["PlatformAdmin", "ShopStaff", "Member", "Anonymous"]
STAFF_ROLES = ["PlatformAdmin", "ShopStaff"]


def _validate_overrides(data):
    overrides = data.get("ship_state_overrides")
    if overrides is None:
        return []
    if not isinstance(overrides, list):
        raise invalid_request("Field 'ship_state_overrides' must be an array")
    for entry in overrides:
        if not isinstance(entry, dict):
            raise invalid_request("ship_state_overrides entries must be objects")
        state = entry.get("state_code") or entry.get("state")
        status = entry.get("status")
        if not isinstance(state, str) or not isinstance(status, str):
            raise invalid_request(
                "ship_state_overrides entries need state_code and status")
    return overrides


@bp.post("/skus")
def create_sku():
    require(STAFF_ROLES)
    data = body()
    # FK existence first (priority 3)
    category_id = data.get("category_id")
    if category_id is not None:
        if not isinstance(category_id, str):
            raise invalid_request("Field 'category_id' must be a string")
        get_or_404(db["categories"], category_id)
    # shape (priority 4)
    category_id = req_str(data, "category_id")
    get_or_404(db["categories"], category_id)
    sku_code = req_str(data, "sku_code", min_len=3, max_len=32)
    title = req_str(data, "title")
    base_price_cents = req_int(data, "base_price_cents", min_v=0)
    abv = req_int(data, "abv_basis_points", min_v=0, max_v=500)
    overrides = _validate_overrides(data)
    discontinued = opt_bool(data, "discontinued", False)
    # uniqueness (priority 12)
    for sku in db["skus"].values():
        if sku["sku_code"] == sku_code:
            raise duplicate("sku_code already exists")
    category = db["categories"][category_id]
    ent = new_entity({
        "category_id": category_id,
        "sku_code": sku_code,
        "title": title,
        "base_price_cents": base_price_cents,
        "abv_basis_points": abv,
        "age_neutral_class": compute_age_neutral_class(category, abv),
        "ship_state_overrides": overrides,
        "discontinued": discontinued,
        "on_hand_cached": 0,
    })
    db["skus"][ent["id"]] = ent
    return success(public(ent), status=201)


@bp.get("/skus")
def list_skus():
    require(READ_ROLES)
    limit, offset = pagination_params()
    category_id = request.args.get("category_id")
    discontinued = parse_bool_param("discontinued")
    items = list(db["skus"].values())
    if category_id is not None:
        items = [s for s in items if s["category_id"] == category_id]
    if discontinued is not None:
        items = [s for s in items if s["discontinued"] == discontinued]
    page, pg = paginate(items, limit, offset)
    return success([public(s) for s in page], response_type="array",
                   pagination=pg)


@bp.get("/skus/<sid>")
def get_sku(sid):
    require(READ_ROLES)
    ent = get_or_404(db["skus"], sid)
    return success(public(ent))


@bp.patch("/skus/<sid>")
def update_sku(sid):
    require(STAFF_ROLES)
    ent = get_or_404(db["skus"], sid)
    data = body()
    changed = False
    if "title" in data:
        ent["title"] = req_str(data, "title")
        changed = True
    if "base_price_cents" in data:
        ent["base_price_cents"] = req_int(data, "base_price_cents", min_v=0)
        changed = True
    if "abv_basis_points" in data:
        ent["abv_basis_points"] = req_int(data, "abv_basis_points",
                                          min_v=0, max_v=500)
        changed = True
    if "discontinued" in data:
        if not isinstance(data["discontinued"], bool):
            raise invalid_request("Field 'discontinued' must be a boolean")
        ent["discontinued"] = data["discontinued"]
        changed = True
    if "ship_state_overrides" in data:
        ent["ship_state_overrides"] = _validate_overrides(data)
        changed = True
    if changed:
        category = db["categories"].get(ent["category_id"])
        if category is not None:
            ent["age_neutral_class"] = compute_age_neutral_class(
                category, ent["abv_basis_points"])
        touch(ent)
    return success(public(ent))


@bp.get("/skus/<sid>/flight-items")
def sku_flight_items(sid):
    require(STAFF_ROLES)
    get_or_404(db["skus"], sid)
    limit, offset = pagination_params()
    items = [f for f in db["flight_items"].values() if f["sku_id"] == sid]
    page, pg = paginate(items, limit, offset)
    return success([public(f) for f in page], response_type="array",
                   pagination=pg)


@bp.get("/skus/<sid>/special-orders")
def sku_special_orders(sid):
    require(STAFF_ROLES)
    get_or_404(db["skus"], sid)
    limit, offset = pagination_params()
    items = [s for s in db["special_orders"].values()
             if s.get("resolved_sku_id") == sid]
    page, pg = paginate(items, limit, offset)
    return success([public(s) for s in page], response_type="array",
                   pagination=pg)


@bp.get("/skus/<sid>/order-lines")
def sku_order_lines(sid):
    require(STAFF_ROLES)
    get_or_404(db["skus"], sid)
    limit, offset = pagination_params()
    items = [l for l in db["order_lines"].values() if l["sku_id"] == sid]
    page, pg = paginate(items, limit, offset)
    return success([public(l) for l in page], response_type="array",
                   pagination=pg)


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------

@bp.post("/skus/<sid>/lots")
def create_lot(sid):
    require(STAFF_ROLES)
    sku = get_or_404(db["skus"], sid)
    data = body()
    lot_code = req_str(data, "lot_code")
    qty_received = req_int(data, "qty_received", min_v=1)
    unit_cost_cents = req_int(data, "unit_cost_cents", min_v=0)
    expires_on = req_date(data, "expires_on")
    quarantine_reason = opt_str(data, "quarantine_reason")
    for lot in db["lots"].values():
        if lot["sku_id"] == sid and lot["lot_code"] == lot_code:
            raise duplicate("(sku_id, lot_code) already exists")
    ent = new_entity({
        "sku_id": sid,
        "lot_code": lot_code,
        "qty_received": qty_received,
        "qty_remaining": qty_received,
        "unit_cost_cents": unit_cost_cents,
        "expires_on": expires_on,
        "status": "ACTIVE",
        "quarantine_reason": quarantine_reason,
    })
    recompute_lot_status(ent)
    db["lots"][ent["id"]] = ent
    recompute_on_hand(sid)
    return success(public(ent), status=201)


@bp.get("/skus/<sid>/lots")
def list_lots(sid):
    require(STAFF_ROLES)
    get_or_404(db["skus"], sid)
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = [l for l in db["lots"].values() if l["sku_id"] == sid]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, pg = paginate(items, limit, offset)
    return success([public(l) for l in page], response_type="array",
                   pagination=pg)


@bp.get("/lots/<lid>")
def get_lot(lid):
    require(STAFF_ROLES)
    ent = get_or_404(db["lots"], lid)
    return success(public(ent))


@bp.post("/lots/<lid>/quarantine")
def quarantine_lot(lid):
    require(["ComplianceOfficer"])
    data = body()
    reason = req_str(data, "quarantine_reason")
    ent = get_or_404(db["lots"], lid)
    ent["status"] = "QUARANTINED"
    ent["quarantine_reason"] = reason
    touch(ent)
    recompute_on_hand(ent["sku_id"])
    return success(public(ent))


@bp.post("/lots/<lid>/release-quarantine")
def release_lot(lid):
    require(["ComplianceOfficer"])
    ent = get_or_404(db["lots"], lid)
    if ent["status"] != "QUARANTINED":
        from errors import invalid_state
        raise invalid_state("Lot is not quarantined")
    ent["status"] = "ACTIVE"
    ent["quarantine_reason"] = None
    recompute_lot_status(ent)
    touch(ent)
    recompute_on_hand(ent["sku_id"])
    return success(public(ent))
