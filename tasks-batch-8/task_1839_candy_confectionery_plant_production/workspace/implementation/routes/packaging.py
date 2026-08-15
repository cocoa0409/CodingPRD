"""Packaging components and purchase orders (PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint, request

from db import new_id, now, stamp_new, store, touch
from errors import ApiError
from middleware import ALL_ROLES, auth, body, is_int, paginate, require_fields
from response import success_list, success_object
from serializers import packaging_component_json, purchase_order_json

packaging_bp = Blueprint("packaging", __name__)


def get_component_or_404(cid):
    c = store.packaging_components.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", "Packaging component not found: %s" % cid)
    return c


def get_po_or_404(pid):
    po = store.purchase_orders.get(pid)
    if po is None:
        raise ApiError("ERR_NOT_FOUND", "Purchase order not found: %s" % pid)
    return po


def sync_available(component):
    """qty_available is always exactly qty_on_hand - qty_reserved, recomputed
    on every mutation of either operand (PRD §2.11)."""
    component["qty_available"] = component["qty_on_hand"] - component["qty_reserved"]


@packaging_bp.route("/packaging-components", methods=["POST"])
def create_packaging_component():
    auth(("ProductionPlanner",))
    b = body()
    require_fields(b, ["sku_code", "name", "units_per_component", "lead_time_days", "qty_on_hand"])
    if not isinstance(b["sku_code"], str) or not b["sku_code"]:
        raise ApiError("ERR_INVALID_REQUEST", "sku_code is required and must be a non-empty string.")
    if not isinstance(b["name"], str) or not b["name"]:
        raise ApiError("ERR_INVALID_REQUEST", "name is required and must be a non-empty string.")
    if not is_int(b["units_per_component"]) or b["units_per_component"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", "units_per_component must be an integer >= 1.")
    if not is_int(b["lead_time_days"]) or b["lead_time_days"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", "lead_time_days must be an integer >= 0.")
    if not is_int(b["qty_on_hand"]) or b["qty_on_hand"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", "qty_on_hand must be an integer >= 0.")
    for c in store.packaging_components.values():
        if c["sku_code"] == b["sku_code"]:
            raise ApiError("ERR_INVALID_REQUEST", "sku_code must be unique.")
    c = {
        "id": new_id(),
        "sku_code": b["sku_code"],
        "name": b["name"],
        "units_per_component": b["units_per_component"],
        "lead_time_days": b["lead_time_days"],
        "qty_on_hand": b["qty_on_hand"],
        "qty_reserved": 0,
    }
    sync_available(c)
    stamp_new(c)
    store.packaging_components[c["id"]] = c
    return success_object(packaging_component_json(c), 201)


@packaging_bp.route("/packaging-components", methods=["GET"])
def list_packaging_components():
    auth(ALL_ROLES)
    items = list(store.packaging_components.values())
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return success_list([packaging_component_json(c) for c in page], meta)


@packaging_bp.route("/packaging-components/<cid>/purchase-orders", methods=["POST"])
def create_purchase_order(cid):
    auth(("ProductionPlanner",))
    component = get_component_or_404(cid)
    b = body()
    require_fields(b, ["order_qty"])
    if not is_int(b["order_qty"]) or b["order_qty"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "order_qty must be an integer > 0.")
    ordered_at = now()
    po = {
        "id": new_id(),
        "component_id": component["id"],
        "order_qty": b["order_qty"],
        "ordered_at": ordered_at,
        # due_at = ordered_at + component.lead_time_days days
        "due_at": ordered_at + timedelta(days=component["lead_time_days"]),
        "received_at": None,
        "status": "ORDERED",
    }
    stamp_new(po)
    store.purchase_orders[po["id"]] = po
    return success_object(purchase_order_json(po), 201)


@packaging_bp.route("/purchase-orders", methods=["GET"])
def list_purchase_orders():
    auth(ALL_ROLES)
    items = list(store.purchase_orders.values())
    f = request.args.get("component_id")
    if f is not None:
        items = [po for po in items if po["component_id"] == f]
    items.sort(key=lambda po: po["created_at"])
    page, meta = paginate(items)
    return success_list([purchase_order_json(po) for po in page], meta)


@packaging_bp.route("/purchase-orders/<pid>", methods=["GET"])
def get_purchase_order(pid):
    auth(ALL_ROLES)
    return success_object(purchase_order_json(get_po_or_404(pid)))


@packaging_bp.route("/purchase-orders/<pid>/receive", methods=["POST"])
def receive_purchase_order(pid):
    auth(("ProductionPlanner",))
    po = get_po_or_404(pid)
    # State gate: a second receipt attempt fails with ERR_INVALID_STATE.
    if po["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_STATE", "Purchase order is not ORDERED.")
    # Temporal gate: receipt requires the logical clock to have reached due_at.
    if now() < po["due_at"]:
        raise ApiError("ERR_PO_NOT_DUE", "Purchase order cannot be received before due_at.")
    po["received_at"] = now()
    po["status"] = "RECEIVED"
    touch(po)
    # Ledger sync: stock lands on the component; qty_available recomputes.
    component = store.packaging_components[po["component_id"]]
    component["qty_on_hand"] += po["order_qty"]
    sync_available(component)
    touch(component)
    return success_object(purchase_order_json(po))
