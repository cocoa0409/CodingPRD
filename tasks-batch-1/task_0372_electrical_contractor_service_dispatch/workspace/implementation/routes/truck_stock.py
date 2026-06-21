"""TruckStockItem endpoints (PRD §3.2).

Stock records technician_id, sku_id, opening quantity_on_hand, reorder_threshold
(default 0). low_stock = (quantity_on_hand <= reorder_threshold), recomputed on
every change. Restock adds add_quantity and recomputes low_stock.
"""
from flask import Blueprint, request

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_fields,
                     require_nonneg_int, require_positive_int, serialize,
                     serialize_list, sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("truck_stock", __name__)


def recompute_low_stock(item):
    item["low_stock"] = item["quantity_on_hand"] <= item["reorder_threshold"]


@bp.post("/v1/truck-stock-items")
def create_stock_item():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["technician_id", "sku_id", "quantity_on_hand"])

    # Existence: technician_id then sku_id (left-to-right).
    technician = db.technicians.get(body["technician_id"])
    if technician is None:
        raise err("ERR_NOT_FOUND", "Technician not found")
    sku = db.material_skus.get(body["sku_id"])
    if sku is None:
        raise err("ERR_NOT_FOUND", "SKU not found")

    require_nonneg_int(body["quantity_on_hand"], "quantity_on_hand")
    reorder_threshold = body.get("reorder_threshold", 0)
    if reorder_threshold is None:
        reorder_threshold = 0
    require_nonneg_int(reorder_threshold, "reorder_threshold")

    record = {
        "technician_id": technician["id"],
        "sku_id": sku["id"],
        "quantity_on_hand": body["quantity_on_hand"],
        "reorder_threshold": reorder_threshold,
    }
    recompute_low_stock(record)
    db.stamp_new(record)
    db.truck_stock_items[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/truck-stock-items/<stock_item_id>")
def get_stock_item(stock_item_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    record = db.truck_stock_items.get(stock_item_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Truck-stock item not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/truck-stock-items")
def list_stock_items():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    limit, offset = parse_pagination()
    technician_id = request.args.get("technician_id")
    sku_id = request.args.get("sku_id")

    items = list(db.truck_stock_items.values())
    if technician_id is not None:
        items = [i for i in items if i["technician_id"] == technician_id]
    if sku_id is not None:
        items = [i for i in items if i["sku_id"] == sku_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/truck-stock-items/<stock_item_id>/restock")
def restock(stock_item_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    record = db.truck_stock_items.get(stock_item_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Truck-stock item not found")
    body = get_json_body()
    require_fields(body, ["add_quantity"])
    require_positive_int(body["add_quantity"], "add_quantity")

    record["quantity_on_hand"] += body["add_quantity"]
    recompute_low_stock(record)
    db.touch(record)
    return response.object_response(serialize(record), 200)
