"""Durable medical equipment inventory and orders (PRD 3.9)."""

from flask import Blueprint

import cascades
import config
from envelope import created, listing, ok
from errors import (
    ERR_INSUFFICIENT_INVENTORY, ERR_PRIOR_AUTH_REQUIRED, ERR_SCHEDULE_CONFLICT, api_error,
)
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, pagination, paginate,
    path_row, query_filters, raw_body, require_order, state, touch, validate,
)
from store import ordered, store

bp = Blueprint("dme", __name__)


@bp.post("/palliative/dme-inventory")
def create_inventory_item():
    auth([config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("device_type", "enum", required=True, enum=config.DEVICE_TYPES),
        field("total_units", "integer", required=True, lo=1, hi=500),
        field("prior_auth_required", "boolean", default=False),
    ])
    row = store.new_row({
        "device_type": data["device_type"],
        "total_units": data["total_units"],
        "prior_auth_required": bool(data["prior_auth_required"]),
        "available_units": data["total_units"],
        "reserved_units": 0,
        "delivered_units": 0,
    })
    store.dme_inventory[row["id"]] = row
    return created(row)


@bp.get("/palliative/dme-inventory/<iid>")
def read_inventory_item(iid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    return ok(path_row(store.dme_inventory, iid))


@bp.post("/palliative/dme-orders")
def create_dme_order():
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("inventory_item_id", "string", required=True),
        field("quantity", "integer", required=True, lo=1, hi=10),
        field("delivery_window_start", "datetime", required=True),
        field("delivery_window_end", "datetime", required=True),
    ])
    require_order(data["delivery_window_start"], data["delivery_window_end"],
                  "delivery_window_start", "delivery_window_end")
    patient = fk(store.patients, data["patient_id"])
    item = fk(store.dme_inventory, data["inventory_item_id"])
    freeze_gate(patient)
    if item["available_units"] < data["quantity"]:
        raise api_error(ERR_INSUFFICIENT_INVENTORY)

    row = store.new_row({
        "patient_id": patient["id"],
        "inventory_item_id": item["id"],
        "quantity": data["quantity"],
        "delivery_window_start": data["delivery_window_start"],
        "delivery_window_end": data["delivery_window_end"],
        "prior_auth_reference": None,
        "delivered_at": None,
        "closed_reason": None,
        "status": "PENDING_AUTH" if item["prior_auth_required"] else "REQUESTED",
    })
    store.dme_orders[row["id"]] = row
    cascades.recompute_inventory(item)
    return created(row)


@bp.post("/palliative/dme-orders/<oid>/authorize")
def authorize_dme_order(oid):
    auth([config.ROLE_ADMIN])
    order = path_row(store.dme_orders, oid)
    body = raw_body()
    data = validate(body, [field("prior_auth_reference", "string", required=True)])
    freeze_gate(store.patients.get(order["patient_id"]))
    state(order["status"] == "PENDING_AUTH")
    order["prior_auth_reference"] = data["prior_auth_reference"]
    order["status"] = "REQUESTED"
    touch(order)
    return ok(order)


@bp.post("/palliative/dme-orders/<oid>/fulfillment")
def fulfil_dme_order(oid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    order = path_row(store.dme_orders, oid)
    body = raw_body()
    data = validate(body, [field("event", "enum", required=True, enum=config.DME_EVENTS)])
    freeze_gate(store.patients.get(order["patient_id"]))

    if data["event"] == "SCHEDULED":
        state(order["status"] in ("REQUESTED", "PENDING_AUTH"))
        if order["status"] == "PENDING_AUTH":
            raise api_error(ERR_PRIOR_AUTH_REQUIRED)
        start, end = order["delivery_window_start"], order["delivery_window_end"]
        for other in store.dme_orders.values():
            if other["id"] == order["id"]:
                continue
            if other["inventory_item_id"] != order["inventory_item_id"]:
                continue
            if other["status"] not in ("REQUESTED", "PENDING_AUTH", "SCHEDULED", "DELIVERED"):
                continue
            if start < other["delivery_window_end"] and other["delivery_window_start"] < end:
                raise api_error(ERR_SCHEDULE_CONFLICT)
        order["status"] = "SCHEDULED"
        touch(order)
    else:
        state(order["status"] == "SCHEDULED")
        order["status"] = "DELIVERED"
        order["delivered_at"] = store.now()
        touch(order)
        cascades.recompute_inventory(store.dme_inventory[order["inventory_item_id"]])
    return ok(order)


@bp.post("/palliative/dme-orders/<oid>/close")
def close_dme_order(oid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    order = path_row(store.dme_orders, oid)
    body = raw_body()
    data = validate(body, [
        field("closed_reason", "enum", required=True, enum=config.DME_CLOSED_REASONS),
    ])
    # Permitted after a patient's death — no records-freeze gate here.
    if data["closed_reason"] == "CANCELLED":
        state(order["status"] in ("REQUESTED", "PENDING_AUTH", "SCHEDULED"))
    else:
        state(order["status"] == "DELIVERED")
    order["status"] = "CLOSED"
    order["closed_reason"] = data["closed_reason"]
    touch(order)
    cascades.recompute_inventory(store.dme_inventory[order["inventory_item_id"]])
    return ok(order)


@bp.get("/palliative/dme-orders/<oid>")
def read_dme_order(oid):
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    return ok(path_row(store.dme_orders, oid))


@bp.get("/palliative/dme-orders")
def list_dme_orders():
    auth([config.ROLE_NURSE, config.ROLE_ADMIN])
    limit, offset = pagination()
    rows = apply_filters(ordered(store.dme_orders.values()),
                         query_filters(["patient_id", "inventory_item_id", "status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
