"""Stock lot endpoints (PRD 3.1, 3.7)."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, require_roles
from response import success_object
from routes.helpers import STAFF_ROLES, get_one, list_response, public
from services import lot_available, new_record, sweep_backorders_for_lot, touch
from validate import get_body, req_date, req_int, req_str, require_path_resource, require_ref

bp = Blueprint("stock_lots", __name__)


def ser_lot(lot):
    out = public(lot)
    out["qty_available"] = lot_available(lot)
    return out


@bp.post("/pool-supply/stock-lots")
def create_lot():
    caller = get_caller()
    require_roles(caller, ["WarehouseLead"])
    body = get_body()
    branch_id = req_str(body, "branch_id")
    product_id = req_str(body, "product_id")
    lot_code = req_str(body, "lot_code")
    qty_on_hand = req_int(body, "qty_on_hand", minimum=0)
    require_ref("branches", branch_id, "branch_id")
    product = require_ref("products", product_id, "product_id")
    expiry_date = body.get("expiry_date")
    if product["expiry_tracked"]:
        if expiry_date is None:
            raise_error(ERR_INVALID_REQUEST, "expiry_date is required for expiry-tracked products")
        req_date(body, "expiry_date")
    else:
        if expiry_date is not None:
            raise_error(ERR_INVALID_REQUEST, "expiry_date only allowed for expiry-tracked products")
        expiry_date = None
    rec = new_record("stock_lots", {
        "branch_id": branch_id,
        "product_id": product_id,
        "lot_code": lot_code,
        "qty_on_hand": qty_on_hand,
        "qty_reserved_willcall": 0,
        "qty_reserved_route": 0,
        "expiry_date": expiry_date,
        "hazmat_storage_class": product["hazmat_class"],  # copied and frozen
    })
    return success_object(ser_lot(rec), status=201)


@bp.get("/pool-supply/stock-lots")
def list_lots():
    filters = {
        "branch_id": request.args.get("branch_id"),
        "product_id": request.args.get("product_id"),
    }
    return list_response("stock_lots", STAFF_ROLES, filters, serializer=ser_lot)


@bp.get("/pool-supply/stock-lots/<rid>")
def get_lot(rid):
    return get_one("stock_lots", rid, STAFF_ROLES, serializer=ser_lot)


@bp.post("/pool-supply/stock-lots/<rid>/replenish")
def replenish_lot(rid):
    caller = get_caller()
    require_roles(caller, ["WarehouseLead"])
    lot = require_path_resource("stock_lots", rid)
    body = get_body()
    add_qty = req_int(body, "add_qty", minimum=1)
    lot["qty_on_hand"] += add_qty
    touch(lot)
    sweep_backorders_for_lot(lot)  # automatic waterfall; posture is recomputed on read
    return success_object(ser_lot(lot))
