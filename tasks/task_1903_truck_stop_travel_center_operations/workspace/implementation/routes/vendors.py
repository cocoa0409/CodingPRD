"""Vendors and vendor price lists (PRD 3.6)."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from routes.helpers import list_from, list_response, public
from services.core import new_record
from validate import (
    get_body, opt_int, req_enum, req_int, req_str, require_path_resource,
)

bp = Blueprint("vendors", __name__)

VENDOR_CATEGORIES = ["FUEL", "DEF_OIL", "FOOD", "GENERAL"]
READ_ROLES = ["GeneralManager", "ShiftManager", "MaintenanceTech"]


@bp.post("/sites/<sid>/vendors")
def create_vendor(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    name = req_str(body, "name")
    category = req_enum(body, "category", VENDOR_CATEGORIES)
    rec = new_record("vendors", {
        "site_id": site["id"],
        "name": name,
        "category": category,
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/vendors")
def list_vendors(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    return list_response("vendors", {"site_id": sid})


@bp.get("/vendors/<rid>")
def get_vendor(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("vendors", rid)
    return success_object(public(rec))


@bp.post("/vendors/<rid>/price-list")
def add_vendor_price(rid):
    authorized(["GeneralManager"])
    vendor = require_path_resource("vendors", rid)
    body = get_body()
    item_sku = req_str(body, "item_sku")
    unit = req_str(body, "unit")
    unit_price = req_int(body, "unit_price_cents", non_negative=True)
    pack_size = opt_int(body, "pack_size", 1, positive=True)
    rec = new_record("vendor_prices", {
        "vendor_id": vendor["id"],
        "item_sku": item_sku,
        "unit": unit,
        "unit_price_cents": unit_price,
        "pack_size": pack_size,
    })
    return success_object(public(rec), status=201)


@bp.get("/vendors/<rid>/price-list")
def list_vendor_prices(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    vendor = require_path_resource("vendors", rid)
    prices = [p for p in db["vendor_prices"].values() if p["vendor_id"] == vendor["id"]]
    return list_from(prices)


@bp.get("/vendors/<rid>/stock-items")
def vendor_stock_items(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    vendor = require_path_resource("vendors", rid)
    items = [i for i in db["stock_items"].values() if i["vendor_id"] == vendor["id"]]
    return list_from(items)


@bp.get("/vendors/<rid>/purchase-orders")
def vendor_purchase_orders(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    vendor = require_path_resource("vendors", rid)
    pos = [p for p in db["purchase_orders"].values() if p["vendor_id"] == vendor["id"]]
    return list_from(pos)


@bp.get("/vendors/<rid>/deliveries")
def vendor_deliveries(rid):
    authorized(["GeneralManager", "FuelDeskLead"])
    vendor = require_path_resource("vendors", rid)
    deliveries = [d for d in db["bulk_deliveries"].values() if d["vendor_id"] == vendor["id"]]
    return list_from(deliveries)
