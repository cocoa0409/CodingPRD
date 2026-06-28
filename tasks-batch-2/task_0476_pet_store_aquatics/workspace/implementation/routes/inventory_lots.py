"""InventoryLot endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
from db import stamp_create, touch
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int, as_datetime,
)
from services.serialize import lot_out

bp = Blueprint("inventory_lots", __name__)

READ_ROLES = ["InventoryManager", "LivestockKeeper", "ClinicVet", "StoreClerk", "Customer"]


@bp.route("/inventory-lots", methods=["POST"])
def create_lot():
    _, role = require_auth()
    require_role(role, ["InventoryManager"])
    body = get_body()
    store_id = as_str(require_present(body, "store_id"), "store_id")
    product_id = as_str(require_present(body, "product_id"), "product_id")
    lot_code = as_str(require_present(body, "lot_code"), "lot_code")
    # FK existence (step 5) before field ranges/uniqueness.
    lookup("stores", store_id)
    lookup("products", product_id)

    qoh = as_int(require_present(body, "quantity_on_hand"), "quantity_on_hand")
    if qoh < 0:
        raise err("ERR_INVALID_FIELD_VALUE", "quantity_on_hand must be >= 0.")
    received_at_raw = require_present(body, "received_at")
    as_datetime(received_at_raw, "received_at")
    expiry_date_raw = require_present(body, "expiry_date")
    as_datetime(expiry_date_raw, "expiry_date")

    # Uniqueness: lot_code unique per product_id (PRD §2.7).
    for lot in db.inventory_lots.values():
        if lot["product_id"] == product_id and lot["lot_code"] == lot_code:
            raise err("ERR_DUPLICATE_RESOURCE", "lot_code must be unique per product.")

    record = {
        "store_id": store_id,
        "product_id": product_id,
        "lot_code": lot_code,
        "quantity_on_hand": qoh,
        "quantity_reserved": 0,
        "received_at": received_at_raw,
        "expiry_date": expiry_date_raw,
        "status": "AVAILABLE",
    }
    stamp_create(record)
    db.inventory_lots[record["id"]] = record
    return object_response(lot_out(record), 201)


@bp.route("/inventory-lots", methods=["GET"])
def list_lots():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.inventory_lots.values())
    store_id = request.args.get("store_id")
    if store_id is not None:
        records = [r for r in records if r["store_id"] == store_id]
    product_id = request.args.get("product_id")
    if product_id is not None:
        records = [r for r in records if r["product_id"] == product_id]
    page, total = paginate(records, limit, offset)
    return array_response([lot_out(r) for r in page], limit, offset, total)


@bp.route("/inventory-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("inventory_lots", lot_id)
    return object_response(lot_out(record))


@bp.route("/inventory-lots/<lot_id>/adjust", methods=["POST"])
def adjust_lot(lot_id):
    _, role = require_auth()
    require_role(role, ["InventoryManager"])
    lot = lookup("inventory_lots", lot_id)
    body = get_body()
    delta = as_int(require_present(body, "delta"), "delta")
    expected = as_int(require_present(body, "expected_lot_version"), "expected_lot_version")

    # OCC check immediately after existence/field parse, before quantity work
    # (PRD §2.10). There is no separate state precondition for adjust.
    if expected != lot["version"]:
        raise err("ERR_STALE_VERSION", "expected_lot_version does not match.")

    new_qoh = lot["quantity_on_hand"] + delta
    if new_qoh < 0 or new_qoh < lot["quantity_reserved"]:
        raise err(
            "ERR_INVALID_FIELD_VALUE",
            "Resulting quantity_on_hand must stay >= 0 and >= quantity_reserved.",
        )
    lot["quantity_on_hand"] = new_qoh
    if new_qoh == 0:
        lot["status"] = "DEPLETED"
    elif lot["status"] == "DEPLETED" and new_qoh > 0:
        lot["status"] = "AVAILABLE"
    touch(lot)
    return object_response(lot_out(lot))
