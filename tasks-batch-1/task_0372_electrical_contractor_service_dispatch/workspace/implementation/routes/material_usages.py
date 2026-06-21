"""MaterialUsage endpoints (PRD §3.5, §3.2).

Recording a usage computes line_total_cents and debits truck stock (never
negative -> ERR_INSUFFICIENT_STOCK). Voiding restores stock and excludes the
line from future invoices.
"""
from flask import Blueprint, request

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_fields,
                     require_positive_int, serialize, serialize_list,
                     sort_by_created)
from middleware import get_identity, require_roles
from routes.truck_stock import recompute_low_stock

bp = Blueprint("material_usages", __name__)


def _stock_item(technician_id, sku_id):
    for item in db.truck_stock_items.values():
        if item["technician_id"] == technician_id and item["sku_id"] == sku_id:
            return item
    return None


@bp.post("/v1/material-usages")
def create_usage():
    user_id, role = get_identity()
    require_roles(role, {"Technician"})
    body = get_json_body()

    # Existence: job_id, technician_id, sku_id (body FKs, left-to-right).
    require_fields(body, ["job_id"])
    job = db.service_jobs.get(body["job_id"])
    if job is None:
        raise err("ERR_NOT_FOUND", "Service job not found")
    require_fields(body, ["technician_id"])
    technician = db.technicians.get(body["technician_id"])
    if technician is None:
        raise err("ERR_NOT_FOUND", "Technician not found")
    require_fields(body, ["sku_id"])
    sku = db.material_skus.get(body["sku_id"])
    if sku is None:
        raise err("ERR_NOT_FOUND", "SKU not found")

    # Ownership: a technician may only record material against their own truck.
    if technician["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Technicians may only record material on their own truck")

    # Body well-formedness: quantity > 0.
    require_fields(body, ["quantity"])
    require_positive_int(body["quantity"], "quantity")
    quantity = body["quantity"]

    # Stock sufficiency: usage quantity must not exceed quantity_on_hand.
    stock = _stock_item(technician["id"], sku["id"])
    on_hand = stock["quantity_on_hand"] if stock is not None else 0
    if quantity > on_hand:
        raise err("ERR_INSUFFICIENT_STOCK", "Material usage quantity exceeds truck stock on hand")

    line_total = quantity * sku["unit_price_cents"]
    record = {
        "job_id": job["id"],
        "technician_id": technician["id"],
        "sku_id": sku["id"],
        "quantity": quantity,
        "line_total_cents": line_total,
        "voided": False,
    }
    db.stamp_new(record)
    db.material_usages[record["id"]] = record

    # Debit truck stock and recompute low_stock.
    stock["quantity_on_hand"] -= quantity
    recompute_low_stock(stock)
    db.touch(stock)

    return response.object_response(serialize(record), 201)


@bp.get("/v1/material-usages/<usage_id>")
def get_usage(usage_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    record = db.material_usages.get(usage_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Material usage not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/material-usages")
def list_usages():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    limit, offset = parse_pagination()
    job_id = request.args.get("job_id")
    technician_id = request.args.get("technician_id")
    sku_id = request.args.get("sku_id")

    items = list(db.material_usages.values())
    if job_id is not None:
        items = [u for u in items if u["job_id"] == job_id]
    if technician_id is not None:
        items = [u for u in items if u["technician_id"] == technician_id]
    if sku_id is not None:
        items = [u for u in items if u["sku_id"] == sku_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/material-usages/<usage_id>/void")
def void_usage(usage_id):
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Technician"})
    usage = db.material_usages.get(usage_id)
    if usage is None:
        raise err("ERR_NOT_FOUND", "Material usage not found")

    # Ownership: a technician may only void their own truck's usage.
    if role == "Technician" and usage["technician_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Technicians may only void their own usage")

    # State: a usage already voided cannot be voided again.
    if usage["voided"]:
        raise err("ERR_INVALID_STATE", "Material usage is already voided")

    usage["voided"] = True
    db.touch(usage)

    # Restore truck stock and recompute low_stock.
    stock = _stock_item(usage["technician_id"], usage["sku_id"])
    if stock is not None:
        stock["quantity_on_hand"] += usage["quantity"]
        recompute_low_stock(stock)
        db.touch(stock)

    return response.object_response(serialize(usage), 200)
