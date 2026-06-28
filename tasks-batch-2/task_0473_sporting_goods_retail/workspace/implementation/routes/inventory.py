"""Store-inventory routes: create stock row, get, list/filter, receive (PRD §2.5, §3.1)."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts
from helpers import get_body, parse_pagination, paginate, as_int
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404
from services import serializers
from services.inventory import recompute_available, find_row

bp = Blueprint("inventory", __name__)


@bp.route("/store-inventory", methods=["POST"])
@require_roles("PlatformAdmin")
def create_store_inventory():
    body = get_body()
    store_id = body.get("store_id")
    sku_id = body.get("sku_id")
    if not isinstance(store_id, str) or not isinstance(sku_id, str):
        raise errors.invalid_request("store_id and sku_id are required strings")
    # Existence left-to-right (§2.9).
    get_or_404(db.stores, store_id)
    get_or_404(db.skus, sku_id)
    # At most one row per (store_id, sku_id) pair (§2.5).
    if find_row(store_id, sku_id) is not None:
        raise errors.ApiError(errors.ERR_DUPLICATE_INVENTORY_ROW, 409,
                              "A stock row already exists for this store and SKU")

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "store_id": store_id,
        "sku_id": sku_id,
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "available_qty": 0,
    }
    db.store_inventory[rid] = rec
    return success(serializers.store_inventory(rec), 201)


@bp.route("/store-inventory/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "ServiceTech", "Customer", "PriceAdmin")
def get_store_inventory(rid):
    rec = get_or_404(db.store_inventory, rid)
    return success(serializers.store_inventory(rec), 200)


@bp.route("/store-inventory", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "ServiceTech", "Customer", "PriceAdmin")
def list_store_inventory():
    limit, offset = parse_pagination()
    store_id = request.args.get("store_id")
    sku_id = request.args.get("sku_id")
    items = list(db.store_inventory.values())
    if store_id is not None:
        items = [r for r in items if r["store_id"] == store_id]
    if sku_id is not None:
        items = [r for r in items if r["sku_id"] == sku_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.store_inventory(r) for r in page], limit, offset, total)


@bp.route("/store-inventory/<rid>/receive", methods=["POST"])
@require_roles("PlatformAdmin")
def receive_store_inventory(rid):
    rec = get_or_404(db.store_inventory, rid)
    body = get_body()
    quantity = as_int(body, "quantity", required=True, minimum=1)
    expected = as_int(body, "expected_store_inventory_version", required=True)
    # OCC guard on StoreInventory.version (§2.6).
    if expected != rec["version"]:
        raise errors.ApiError(errors.ERR_STALE_INVENTORY_VERSION, 412,
                              "expected_store_inventory_version is stale")
    rec["on_hand_qty"] += quantity
    recompute_available(rec)
    rec["updated_at"] = now_ts()
    rec["version"] += 1
    return success(serializers.store_inventory(rec), 200)
