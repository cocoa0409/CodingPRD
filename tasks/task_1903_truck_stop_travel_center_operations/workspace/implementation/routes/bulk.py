"""Bulk tanks, stick readings, deliveries and reorder suggestions (PRD 3.9)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_WATER_BOTTOM_EXCEEDED,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_from, list_response, public
from services import pricing
from services.core import new_record, recompute_tank_low, touch
from util import dec, rhu_float
from validate import (
    get_body, opt_number, query_filter, req_enum, req_int, req_number,
    require_path_resource, valid_number,
)

bp = Blueprint("bulk", __name__)

PRODUCT_TYPES = ["DIESEL", "DEF", "OIL"]
READ_ROLES = ["GeneralManager", "FuelDeskLead", "ShiftManager"]
WATER_BOTTOM_MAX_INCHES = dec("1.0")


def _check_water_bottom(value):
    """p15: a reported water bottom above 1.0 inches is rejected."""
    if valid_number(value) and dec(value) > WATER_BOTTOM_MAX_INCHES:
        raise_error(ERR_WATER_BOTTOM_EXCEEDED, "water bottom exceeds 1.0 inches")


@bp.post("/sites/<sid>/bulk-tanks")
def create_tank(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    product = req_enum(body, "product_type", PRODUCT_TYPES)
    capacity = req_number(body, "capacity_gallons", positive=True)
    threshold = req_number(body, "reorder_threshold_gallons", non_negative=True)
    safety = req_number(body, "safety_stock_gallons", non_negative=True)
    daily = req_number(body, "daily_usage_gallons", non_negative=True)
    lead = req_int(body, "lead_time_days", non_negative=True)
    initial = opt_number(body, "initial_gallons", 0, non_negative=True)
    rack = opt_number(body, "rack_price_cents_per_gallon_4dp", None, non_negative=True)
    rec = new_record("bulk_tanks", {
        "site_id": site["id"],
        "product_type": product,
        "capacity_gallons": rhu_float(capacity, 2),
        "current_gallons": rhu_float(initial, 2),
        "reorder_threshold_gallons": rhu_float(threshold, 2),
        "safety_stock_gallons": rhu_float(safety, 2),
        "daily_usage_gallons": rhu_float(daily, 2),
        "lead_time_days": lead,
        "rack_price_cents_per_gallon_4dp": rhu_float(rack, 4)
        if (product == "DIESEL" and rack is not None) else None,
        "is_low_stock": False,
    })
    recompute_tank_low(rec)
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/bulk-tanks")
def list_tanks(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {"site_id": sid, "product_type": query_filter("product_type", PRODUCT_TYPES)}
    return list_response("bulk_tanks", filters)


@bp.get("/bulk-tanks/<rid>")
def get_tank(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("bulk_tanks", rid)
    return success_object(public(rec))


@bp.post("/bulk-tanks/<rid>/stick-reading")
def stick_reading(rid):
    authorized(["FuelDeskLead", "GeneralManager"])
    tank = require_path_resource("bulk_tanks", rid)
    body = get_body()
    _check_water_bottom(body.get("water_bottom_inches"))
    reading = req_number(body, "reading_gallons", non_negative=True)
    water = opt_number(body, "water_bottom_inches", 0, non_negative=True)
    tank["current_gallons"] = rhu_float(reading, 2)
    recompute_tank_low(tank)
    touch(tank)
    return success_object(public(tank))


@bp.post("/bulk-tanks/<rid>/deliveries")
def record_delivery(rid):
    authorized(["FuelDeskLead", "GeneralManager"])
    tank = require_path_resource("bulk_tanks", rid)
    body = get_body()
    vendor = None
    if body.get("vendor_id") is not None:
        vendor = db["vendors"].get(body["vendor_id"]) if isinstance(body.get("vendor_id"), str) else None
        if vendor is None:
            raise_error(ERR_NOT_FOUND, "vendor_id does not resolve")
    # p15: fuel-quality gate on the reported water bottom
    _check_water_bottom(body.get("water_bottom_inches"))
    gallons = req_number(body, "gallons_delivered", positive=True)
    water = opt_number(body, "water_bottom_inches", 0, non_negative=True)
    rack = opt_number(body, "rack_price_cents_per_gallon_4dp", None, non_negative=True)
    delivery = new_record("bulk_deliveries", {
        "bulk_tank_id": tank["id"],
        "vendor_id": vendor["id"] if vendor else None,
        "gallons_delivered": rhu_float(gallons, 2),
        "water_bottom_inches": water,
        "rack_price_cents_per_gallon_4dp": rhu_float(rack, 4) if rack is not None else None,
        "status": "DELIVERED",
    }, ledger=True)
    tank["current_gallons"] = rhu_float(dec(tank["current_gallons"]) + dec(gallons), 2)
    if tank["product_type"] == "DIESEL" and rack is not None:
        tank["rack_price_cents_per_gallon_4dp"] = rhu_float(rack, 4)
    recompute_tank_low(tank)
    touch(tank)
    return success_object(public(delivery), status=201)


@bp.get("/bulk-tanks/<rid>/deliveries")
def list_deliveries(rid):
    authorized(["GeneralManager", "FuelDeskLead"])
    tank = require_path_resource("bulk_tanks", rid)
    deliveries = [d for d in db["bulk_deliveries"].values() if d["bulk_tank_id"] == tank["id"]]
    return list_from(deliveries)


@bp.get("/sites/<sid>/reorder-suggestions")
def reorder_suggestions(sid):
    authorized(["GeneralManager", "FuelDeskLead"])
    require_path_resource("sites", sid)
    return success_object({"suggestions": pricing.reorder_suggestions(sid)})
