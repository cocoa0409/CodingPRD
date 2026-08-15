"""Stock items (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import list_from, list_response, public
from services.core import new_record, recompute_stock_low
from validate import (
    get_body, opt_int, opt_number, query_filter, req_enum, req_int, req_str,
    require_path_resource,
)

bp = Blueprint("stock", __name__)

CATEGORIES = ["RESTAURANT", "RETAIL", "SHOP_PART", "PACKAGED_OIL"]
READ_ROLES = ["GeneralManager", "ShiftManager", "Cashier", "MaintenanceTech"]


@bp.post("/sites/<sid>/stock-items")
def create_stock_item(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    sku = req_str(body, "sku")
    name = req_str(body, "name")
    category = req_enum(body, "category", CATEGORIES)
    unit = req_str(body, "unit")
    unit_price = req_int(body, "unit_price_cents", non_negative=True)
    reorder_point = req_int(body, "reorder_point", non_negative=True)
    initial = opt_int(body, "initial_on_hand_quantity", 0, non_negative=True)
    case_pack = opt_number(body, "case_pack_gallons", None, positive=True)
    vendor = None
    if body.get("vendor_id") is not None:
        vendor = db["vendors"].get(body["vendor_id"]) if isinstance(body.get("vendor_id"), str) else None
        if vendor is None:
            raise_error(ERR_NOT_FOUND, "vendor_id does not resolve")
    for item in db["stock_items"].values():
        if item["site_id"] == site["id"] and item["sku"] == sku:
            raise_error(ERR_INVALID_REQUEST, "sku must be unique within the site")
    rec = new_record("stock_items", {
        "site_id": site["id"],
        "sku": sku,
        "name": name,
        "category": category,
        "unit": unit,
        "unit_price_cents": unit_price,
        "on_hand_quantity": initial,
        "reorder_point": reorder_point,
        "is_low_stock": False,
        "vendor_id": vendor["id"] if vendor else None,
        "case_pack_gallons": case_pack if category == "PACKAGED_OIL" else None,
    })
    recompute_stock_low(rec)
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/stock-items")
def list_stock_items(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    low_raw = request.args.get("low_stock")
    low = None
    if low_raw is not None and low_raw != "":
        if low_raw.lower() in ("true", "false"):
            low = low_raw.lower() == "true"
        else:
            raise_error(ERR_INVALID_REQUEST, "low_stock must be true or false")
    filters = {
        "site_id": sid,
        "category": query_filter("category", CATEGORIES),
        "is_low_stock": low,
    }
    return list_response("stock_items", filters)


@bp.get("/stock-items/<rid>")
def get_stock_item(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("stock_items", rid)
    return success_object(public(rec))


@bp.get("/stock-items/<rid>/work-order-parts")
def stock_item_parts(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    item = require_path_resource("stock_items", rid)
    parts = [p for p in db["work_order_parts"].values() if p["stock_item_id"] == item["id"]]
    return list_from(parts)
