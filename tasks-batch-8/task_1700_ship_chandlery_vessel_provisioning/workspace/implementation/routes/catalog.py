"""CatalogItem and StockLot routes."""
from flask import Blueprint, request

import db
from db import stamp_new, touch
from errors import (err_catalog_item_not_found, err_stock_lot_not_found,
                    err_duplicate_sku, err_invalid_request, err_invalid_qty,
                    err_stale_version)
from middleware import require_roles, require_any_authenticated
from response import success_object, success_list, parse_pagination
from services.validate import (get_body, req_string, req_int, opt_int,
                               req_bool, req_enum)

bp = Blueprint("catalog", __name__)

CATEGORIES = ("PROVISIONS", "BONDED", "DECK", "ENGINE", "CABIN")
STORAGE_TIERS = ("BONDED_WAREHOUSE", "COLD_STORE", "DRY_STORE")


# ---------------------------------------------------------------------------
# CatalogItem
# ---------------------------------------------------------------------------

@bp.route("/chandlery/catalog-items", methods=["POST"])
@require_roles("ChandlerOpsManager")
def create_catalog_item(user_id, role):
    body = get_body()
    sku = req_string(body, "sku")
    # SKU uniqueness across the whole catalog (ERR_DUPLICATE_SKU)
    for item in db.catalog_items.values():
        if item["sku"] == sku:
            raise err_duplicate_sku()
    base_price_cents = req_int(body, "base_price_cents")
    if base_price_cents < 1:
        raise err_invalid_request("base_price_cents must be >= 1")
    duty_rate_pct = body.get("duty_rate_pct", 0)
    if isinstance(duty_rate_pct, bool) or not isinstance(duty_rate_pct, (int, float)):
        raise err_invalid_request("invalid numeric field: duty_rate_pct")
    if duty_rate_pct < 0:
        raise err_invalid_request("duty_rate_pct must be >= 0")
    item = {
        "sku": sku,
        "name": req_string(body, "name"),
        "category": req_enum(body, "category", CATEGORIES),
        "bonded_eligible": req_bool(body, "bonded_eligible"),
        "requires_cold_chain": req_bool(body, "requires_cold_chain"),
        "base_price_cents": base_price_cents,
        "duty_rate_pct": duty_rate_pct,
    }
    stamp_new(item)
    db.catalog_items[item["id"]] = item
    return success_object(item, status=201)


@bp.route("/chandlery/catalog-items", methods=["GET"])
@require_any_authenticated
def list_catalog_items(user_id, role):
    category = request.args.get("category")
    cold = request.args.get("requires_cold_chain")
    items = list(db.catalog_items.values())
    if category is not None:
        items = [i for i in items if i["category"] == category]
    if cold is not None:
        want = cold.strip().lower() in ("true", "1", "yes")
        items = [i for i in items if bool(i["requires_cold_chain"]) == want]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


# ---------------------------------------------------------------------------
# StockLot
# ---------------------------------------------------------------------------

@bp.route("/chandlery/stock-lots", methods=["POST"])
@require_roles("WarehouseSupervisor")
def create_stock_lot(user_id, role):
    body = get_body()
    catalog_item_id = body.get("catalog_item_id")
    if not isinstance(catalog_item_id, str) or catalog_item_id.strip() == "":
        raise err_invalid_request("missing or invalid field: catalog_item_id")
    if catalog_item_id not in db.catalog_items:
        raise err_catalog_item_not_found()
    lot_code = req_string(body, "lot_code")
    # lot_code unique per catalog_item_id (ERR_DUPLICATE_SKU)
    for lot in db.stock_lots.values():
        if lot["catalog_item_id"] == catalog_item_id and lot["lot_code"] == lot_code:
            raise err_duplicate_sku()
    received_qty = req_int(body, "received_qty", minimum=0)
    capacity_qty = req_int(body, "capacity_qty", minimum=0)
    lot = {
        "catalog_item_id": catalog_item_id,
        "lot_code": lot_code,
        "storage_tier": req_enum(body, "storage_tier", STORAGE_TIERS),
        "received_qty": received_qty,
        "on_hand_qty": received_qty,   # on creation on_hand := received
        "reserved_qty": 0,
        "capacity_qty": capacity_qty,
    }
    stamp_new(lot)
    db.stock_lots[lot["id"]] = lot
    return success_object(lot, status=201)


@bp.route("/chandlery/stock-lots", methods=["GET"])
@require_any_authenticated
def list_stock_lots(user_id, role):
    catalog_item_id = request.args.get("catalog_item_id")
    storage_tier = request.args.get("storage_tier")
    items = list(db.stock_lots.values())
    if catalog_item_id is not None:
        items = [l for l in items if l["catalog_item_id"] == catalog_item_id]
    if storage_tier is not None:
        items = [l for l in items if l["storage_tier"] == storage_tier]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


@bp.route("/chandlery/stock-lots/<lot_id>", methods=["GET"])
@require_any_authenticated
def get_stock_lot(user_id, role, lot_id):
    lot = db.stock_lots.get(lot_id)
    if lot is None:
        raise err_stock_lot_not_found()
    return success_object(lot)


@bp.route("/chandlery/stock-lots/<lot_id>/adjustments", methods=["POST"])
@require_roles("WarehouseSupervisor")
def adjust_stock_lot(user_id, role, lot_id):
    lot = db.stock_lots.get(lot_id)
    if lot is None:
        raise err_stock_lot_not_found()
    body = get_body()
    adjustment_qty = req_int(body, "adjustment_qty")  # may be negative
    req_string(body, "reason")
    expected_version = req_int(body, "expected_stock_lot_version")
    # OCC (priority 6)
    if expected_version != lot["version"]:
        raise err_stale_version()
    # priority 13: neither field negative, on_hand not below reserved
    new_received = lot["received_qty"] + adjustment_qty
    new_on_hand = lot["on_hand_qty"] + adjustment_qty
    if new_received < 0 or new_on_hand < 0:
        raise err_invalid_qty("adjustment would drive a quantity negative")
    if new_on_hand < lot["reserved_qty"]:
        raise err_invalid_qty("on_hand_qty may not be driven below reserved_qty")
    lot["received_qty"] = new_received
    lot["on_hand_qty"] = new_on_hand
    touch(lot)
    return success_object(lot)
