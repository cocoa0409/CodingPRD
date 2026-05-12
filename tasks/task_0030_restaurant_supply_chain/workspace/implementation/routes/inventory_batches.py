"""Inventory batches: list, adjust, transfer, dispose."""

from flask import Blueprint, g, request

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("inventory_batches", __name__, url_prefix="/supply-chain/inventory-batches")


def _zone_supports(store_zone, recipe_zone):
    if store_zone == "MIXED":
        return True
    return store_zone == recipe_zone


def _ensure_owner(batch):
    if g.user_role == "StoreManager" and batch["store_id"] != g.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN, "StoreManager may only act on their own store's inventory.")


@bp.route("", methods=["GET"])
@auth_required("StoreManager", "CentralKitchenPlanner", "FinanceController")
def list_inventory():
    limit, offset = helpers.parse_pagination()
    items = list(db.inventory_batches.values())

    store_id = request.args.get("store_id")
    status_filter = request.args.get("status")
    alert_tier = request.args.get("alert_tier")

    if g.user_role == "StoreManager":
        items = [b for b in items if b["store_id"] == g.user_id]
    if store_id:
        items = [b for b in items if b["store_id"] == store_id]
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    if alert_tier:
        items = [b for b in items if b["alert_tier"] == alert_tier]

    items.sort(key=lambda b: b["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.inventory_batch_dict(b) for b in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<bid>/adjust", methods=["POST"])
@auth_required("StoreManager")
def adjust(bid):
    batch = db.inventory_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"InventoryBatch {bid} not found.")
    _ensure_owner(batch)
    if batch["status"] != "ON_HAND":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only ON_HAND batches may be adjusted.")

    body = helpers.get_json_body()
    if "delta" not in body or "reason" not in body:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "delta and reason are required.")
    delta = body["delta"]
    reason = body["reason"]
    if not isinstance(delta, int):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "delta must be an integer.")
    helpers.check_occ(batch, body.get("version"))

    new_qty = batch["quantity_on_hand"] + delta
    if new_qty < 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Adjustment would yield negative on-hand.")

    batch["quantity_on_hand"] = new_qty
    if new_qty == 0:
        batch["status"] = "DEPLETED"
    helpers.bump(batch)
    audit.append(target_type="InventoryBatch", target_id=bid, action="ADJUST_STOCK",
                 payload={"delta": delta, "reason": reason, "new_quantity_on_hand": new_qty})
    return response.ok(serializers.inventory_batch_dict(batch))


@bp.route("/<bid>/transfer", methods=["POST"])
@auth_required("StoreManager")
def transfer(bid):
    batch = db.inventory_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"InventoryBatch {bid} not found.")
    _ensure_owner(batch)
    if batch["status"] != "ON_HAND":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only ON_HAND batches may be transferred.")

    body = helpers.get_json_body()
    dest_id = body.get("destination_store_id")
    if not dest_id:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "destination_store_id is required.")
    dest = db.stores.get(dest_id)
    if dest is None:
        errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, "Destination store not found.")

    # Priority: TIER3 disposal-required (priority 8) before temperature compatibility (priority 9).
    if batch["alert_tier"] == "TIER3":
        errors.raise_error(errors.ERR_TIER3_DISPOSAL_REQUIRED,
                           "TIER3 batches must be disposed; transfer is forbidden.")
    recipe = db.recipes[batch["recipe_id"]]
    if not _zone_supports(dest["temperature_zone"], recipe["temperature_zone"]):
        errors.raise_error(errors.ERR_TEMPERATURE_ZONE_INCOMPATIBLE,
                           "Destination store does not support the recipe's temperature zone.")
    if dest["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Destination store is not ACTIVE.")
    if batch["alert_tier"] not in ("TIER1", "TIER2"):
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Only TIER1 or TIER2 batches may be transferred (no near-expiry justification).")

    # Source -> TRANSFERRED_OUT
    qty = batch["quantity_on_hand"]
    batch["status"] = "TRANSFERRED_OUT"
    helpers.bump(batch)

    # Create destination inventory batch.
    new_id = db.new_id()
    common = helpers.common_create()
    new_batch = {
        "id": new_id,
        "store_id": dest_id,
        "recipe_id": recipe["id"],
        "production_batch_id": batch["production_batch_id"],
        "quantity_on_hand": qty,
        "received_at": clock.now(),
        "expires_at": batch["expires_at"],
        "alert_tier": "NONE",
        "status": "ON_HAND",
        **common,
    }
    db.inventory_batches[new_id] = new_batch

    audit.append(target_type="InventoryBatch", target_id=bid, action="INTER_STORE_TRANSFER",
                 payload={"source_store_id": batch["store_id"],
                          "destination_store_id": dest_id,
                          "quantity_transferred": qty,
                          "destination_inventory_batch_id": new_id,
                          "recipe_id": recipe["id"]},
                 external_systems=["FINANCE"])
    audit.append(target_type="InventoryBatch", target_id=new_id, action="RECEIVE_TRANSFER",
                 payload={"source_inventory_batch_id": bid,
                          "quantity_on_hand": qty})
    return response.ok(serializers.inventory_batch_dict(batch))


@bp.route("/<bid>/dispose", methods=["POST"])
@auth_required("StoreManager")
def dispose(bid):
    batch = db.inventory_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"InventoryBatch {bid} not found.")
    _ensure_owner(batch)
    if batch["status"] != "ON_HAND":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only ON_HAND batches may be disposed.")

    expires = batch["expires_at"]
    is_tier3 = batch["alert_tier"] == "TIER3"
    is_expired = expires is not None and clock.now() >= expires
    if not (is_tier3 or is_expired):
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Disposal requires alert_tier=TIER3 or expired stock.")

    qty = batch["quantity_on_hand"]
    batch["status"] = "DISPOSED"
    helpers.bump(batch)

    recipe = db.recipes[batch["recipe_id"]]

    # Auto-create LossRecord (cause=SPOILAGE).
    loss_id = db.new_id()
    common = helpers.common_create()
    loss = {
        "id": loss_id,
        "store_id": batch["store_id"],
        "inventory_batch_id": bid,
        "quantity_lost": qty,
        "cause": "SPOILAGE",
        "responsibility_user_id": None,
        "financial_impact_cents": qty * recipe["unit_price_cents"],
        "is_abnormal": False,
        "investigation_status": "NONE",
        "status": "RECORDED",
        **common,
    }
    db.loss_records[loss_id] = loss

    audit.append(target_type="InventoryBatch", target_id=bid, action="DISPOSE_STOCK",
                 payload={"quantity_disposed": qty,
                          "auto_loss_record_id": loss_id,
                          "disposal_archive": {
                              "inventory_batch_id": bid,
                              "store_id": batch["store_id"],
                              "recipe_id": recipe["id"],
                              "quantity_disposed": qty,
                              "disposed_at": clock.iso_format(clock.now()),
                          }})
    audit.append(target_type="LossRecord", target_id=loss_id, action="AUTO_LOSS_FROM_DISPOSAL",
                 payload={"inventory_batch_id": bid, "quantity_lost": qty, "cause": "SPOILAGE"})
    return response.ok(serializers.inventory_batch_dict(batch))
