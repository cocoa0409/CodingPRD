"""InventoryLot read endpoints (PRD §4)."""
from flask import Blueprint, request

from db import store
from middleware import get_auth, require_roles
from response import success
from common import get_lot, parse_pagination, paginate
from serializers import serialize_lot

bp = Blueprint("inventory_lots", __name__)

READ_ROLES = {"ReceivingClerk", "WavePlanner", "ClientUser", "BillingClerk"}


@bp.route("/inventory-lots", methods=["GET"])
def list_lots():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.inventory_lots.values())
    for key in ("client_id", "sku_id", "bin_id", "receipt_id"):
        val = request.args.get(key)
        if val is not None:
            items = [l for l in items if l.get(key) == val]
    page, meta = paginate(items, limit, offset)
    return success([serialize_lot(r) for r in page], pagination=meta)


@bp.route("/inventory-lots/<lot_id>", methods=["GET"])
def get_one_lot(lot_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_lot(lot_id)
    return success(serialize_lot(rec))
