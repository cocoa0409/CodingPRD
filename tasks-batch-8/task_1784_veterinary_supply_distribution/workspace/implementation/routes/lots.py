"""InventoryLot endpoints (PRD 3.2). Receiving stock wakes the backorder
waterfall for the product."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_LOT_EXPIRY
from middleware import authorized
from response import success_object, success_list
from services.calculations import run_backorder_waterfall
from services.core import (
    get_body, require_fields, require_string, require_int, parse_date_field,
    public, get_or_404, paginate,
)
from util import CLOCK, new_id, now_ts

bp = Blueprint("lots", __name__)

READ_ROLES = ["AccountManager", "SupplyChainPlanner", "ComplianceOfficer"]


def _serialize(lot):
    out = public(lot)
    out["expiry_date"] = lot["expiry_date"].isoformat()
    return out


@bp.route("/vet/inventory-lots", methods=["POST"])
def create_lot():
    authorized(["SupplyChainPlanner"])
    body = get_body()
    require_fields(body, ["product_id", "lot_number", "expiry_date", "qty_on_hand"])
    product = get_or_404("products", body["product_id"])
    lot_number = require_string(body, "lot_number")
    expiry_date = parse_date_field(body, "expiry_date")
    qty_on_hand = require_int(body, "qty_on_hand", minimum=1)

    # expiry_date must be strictly after the current clock date at receiving.
    if expiry_date <= CLOCK.today():
        raise_error(ERR_INVALID_LOT_EXPIRY,
                    "expiry_date must be strictly after the current clock date")

    lot = {
        "id": new_id(),
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
        "product_id": product["id"],
        "lot_number": lot_number,
        "expiry_date": expiry_date,
        "qty_on_hand": qty_on_hand,
        "qty_allocated": 0,
        "qty_available": qty_on_hand,
        "status": "AVAILABLE",
    }
    db["inventory_lots"][lot["id"]] = lot

    # New stock wakes the backorder waterfall for this product (PRD 3.6).
    run_backorder_waterfall(product["id"])

    return success_object(_serialize(lot), status=201)


@bp.route("/vet/inventory-lots", methods=["GET"])
def list_lots():
    authorized(READ_ROLES)
    items = list(db["inventory_lots"].values())
    for param in ("product_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [l for l in items if str(l.get(param)) == val]
    page, total, limit, offset = paginate(items)
    return success_list([_serialize(l) for l in page], total, limit, offset)


@bp.route("/vet/inventory-lots/<lid>", methods=["GET"])
def get_lot(lid):
    authorized(READ_ROLES)
    lot = get_or_404("inventory_lots", lid)
    return success_object(_serialize(lot))
