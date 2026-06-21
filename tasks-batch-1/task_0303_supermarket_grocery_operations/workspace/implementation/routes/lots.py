"""Inventory lot lifecycle: quarantine, release, pull, expire + get/list."""
from flask import Blueprint, request

from auth import require_role
from common import touch, pagination_params, paginate
from clock import clock
from db import db
from errors import (
    ApiError, ERR_LOT_NOT_ACTIVE, ERR_LOT_NOT_QUARANTINED, ERR_LOT_NOT_PULLABLE,
    ERR_LOT_NOT_EXPIRABLE, ERR_LOT_NOT_EXPIRED_YET,
)
from lookup import get_lot, get_product
from inventory import product_inventory_rollup, lot_value
from response import success, list_response
from serializers import ser_lot

bp = Blueprint("lots", __name__)


@bp.route("/inventory-lots", methods=["GET"])
def list_lots():
    require_role("StoreManager", "ReceivingClerk", "InventoryAuditor", "Cashier")
    limit, offset = pagination_params(request.args)
    items = list(db.inventory_lots.values())
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    shipment_id = request.args.get("shipment_id")
    if shipment_id is not None:
        items = [l for l in items if l.get("shipment_id") == shipment_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([ser_lot(l) for l in page], limit, offset, total)


@bp.route("/inventory-lots/<lid>", methods=["GET"])
def get_lot_route(lid):
    require_role("StoreManager", "ReceivingClerk", "InventoryAuditor", "Cashier")
    l = get_lot(lid)
    return success(ser_lot(l))


@bp.route("/inventory-lots/<lid>/quarantine", methods=["POST"])
def quarantine_lot(lid):
    require_role("InventoryAuditor", "StoreManager")
    l = get_lot(lid)
    if l["status"] != "ACTIVE":
        raise ApiError(ERR_LOT_NOT_ACTIVE[0], ERR_LOT_NOT_ACTIVE[1], "lot not active")
    l["status"] = "QUARANTINED"
    touch(l)
    # on_hand_qty unchanged; on_hand_value unchanged. Still run rollup to keep
    # denormalized fields consistent (quarantine lots are still counted).
    product = db.products.get(l["product_id"])
    if product is not None:
        product_inventory_rollup(product)
    return success(ser_lot(l))


@bp.route("/inventory-lots/<lid>/release", methods=["POST"])
def release_lot(lid):
    require_role("InventoryAuditor", "StoreManager")
    l = get_lot(lid)
    if l["status"] != "QUARANTINED":
        raise ApiError(ERR_LOT_NOT_QUARANTINED[0], ERR_LOT_NOT_QUARANTINED[1], "lot not quarantined")
    l["status"] = "ACTIVE"
    touch(l)
    product = db.products.get(l["product_id"])
    if product is not None:
        product_inventory_rollup(product)
    return success(ser_lot(l))


def _write_off(l, new_status):
    """Pull/expire shared write-off: record shrink, zero remaining, cascade rollup."""
    product = db.products.get(l["product_id"])
    shrink = lot_value(product, l) if product is not None else 0
    l["_shrink_value_cents"] = shrink
    l["_terminal_clock"] = clock.now()
    l["remaining_qty"] = 0
    l["status"] = new_status
    touch(l)
    if product is not None:
        product_inventory_rollup(product)


@bp.route("/inventory-lots/<lid>/pull", methods=["POST"])
def pull_lot(lid):
    require_role("InventoryAuditor", "StoreManager")
    l = get_lot(lid)
    if l["status"] not in ("ACTIVE", "QUARANTINED"):
        raise ApiError(ERR_LOT_NOT_PULLABLE[0], ERR_LOT_NOT_PULLABLE[1], "lot not pullable")
    _write_off(l, "PULLED")
    return success(ser_lot(l))


@bp.route("/inventory-lots/<lid>/expire", methods=["POST"])
def expire_lot(lid):
    require_role("InventoryAuditor", "StoreManager")
    l = get_lot(lid)
    if l["status"] not in ("ACTIVE", "QUARANTINED"):
        raise ApiError(ERR_LOT_NOT_EXPIRABLE[0], ERR_LOT_NOT_EXPIRABLE[1], "lot not expirable")
    exp = l.get("_expiration_dt")
    if exp is None or not (exp <= clock.now()):
        raise ApiError(ERR_LOT_NOT_EXPIRED_YET[0], ERR_LOT_NOT_EXPIRED_YET[1], "lot not expired yet")
    _write_off(l, "EXPIRED")
    return success(ser_lot(l))
