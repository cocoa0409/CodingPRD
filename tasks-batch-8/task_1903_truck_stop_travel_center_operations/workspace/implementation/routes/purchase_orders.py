"""Purchase orders with partial receiving (PRD 3.6)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response, public
from services.core import new_record, recompute_stock_low, touch
from validate import (
    get_body, query_filter, require_path_resource, valid_int, valid_str,
)

bp = Blueprint("purchase_orders", __name__)

PO_STATUSES = ["DRAFT", "APPROVED", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"]
READ_ROLES = ["GeneralManager", "MaintenanceTech"]


def _vendor_price_for(vendor_id, sku):
    for p in db["vendor_prices"].values():
        if p["vendor_id"] == vendor_id and p["item_sku"] == sku:
            return p
    return None


@bp.post("/sites/<sid>/purchase-orders")
def create_po(sid):
    authorized(["GeneralManager"])
    site = require_path_resource("sites", sid)
    body = get_body()
    vendor = None
    if body.get("vendor_id") is not None:
        vendor = db["vendors"].get(body["vendor_id"]) if isinstance(body.get("vendor_id"), str) else None
        if vendor is None:
            raise_error(ERR_NOT_FOUND, "vendor_id does not resolve")
    if vendor is None:
        raise_error(ERR_INVALID_REQUEST, "vendor_id is required")
    lines_raw = body.get("lines")
    if not isinstance(lines_raw, list) or not lines_raw:
        raise_error(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    lines = []
    total = 0
    for ln in lines_raw:
        if not isinstance(ln, dict) or not valid_str(ln.get("sku")):
            raise_error(ERR_INVALID_REQUEST, "each line requires an sku")
        qty = ln.get("quantity")
        if not valid_int(qty) or qty <= 0:
            raise_error(ERR_INVALID_REQUEST, "line quantity must be a positive integer")
        price = ln.get("unit_price_cents")
        if price is None:
            vp = _vendor_price_for(vendor["id"], ln["sku"])
            if vp is None:
                raise_error(ERR_INVALID_REQUEST,
                            f"no vendor price for sku {ln['sku']} and unit_price_cents omitted")
            price = vp["unit_price_cents"]
        elif not valid_int(price) or price < 0:
            raise_error(ERR_INVALID_REQUEST, "line unit_price_cents must be a non-negative integer")
        lines.append({"sku": ln["sku"], "quantity": qty, "unit_price_cents": price})
        total += qty * price
    rec = new_record("purchase_orders", {
        "site_id": site["id"],
        "vendor_id": vendor["id"],
        "lines": lines,
        "status": "DRAFT",
        "total_cents": total,
        "received_lines": [],
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/purchase-orders")
def list_pos(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "status": query_filter("status", PO_STATUSES),
        "vendor_id": query_filter("vendor_id"),
    }
    return list_response("purchase_orders", filters)


@bp.get("/purchase-orders/<rid>")
def get_po(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("purchase_orders", rid)
    return success_object(public(rec))


@bp.post("/purchase-orders/<rid>/approve")
def approve_po(rid):
    authorized(["GeneralManager"])
    po = require_path_resource("purchase_orders", rid)
    if po["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "purchase order is not DRAFT")
    po["status"] = "APPROVED"
    touch(po)
    return success_object(public(po))


@bp.post("/purchase-orders/<rid>/receive")
def receive_po(rid):
    authorized(["GeneralManager", "MaintenanceTech"])
    po = require_path_resource("purchase_orders", rid)
    if po["status"] not in ("APPROVED", "PARTIALLY_RECEIVED"):
        raise_error(ERR_INVALID_STATE, "purchase order is not open for receiving")
    body = get_body()
    lines_raw = body.get("received_lines")
    if not isinstance(lines_raw, list) or not lines_raw:
        raise_error(ERR_INVALID_REQUEST, "received_lines must be a non-empty array")
    ordered = {}
    for ln in po["lines"]:
        ordered[ln["sku"]] = ordered.get(ln["sku"], 0) + ln["quantity"]
    already = {}
    for ln in po["received_lines"]:
        already[ln["sku"]] = already.get(ln["sku"], 0) + ln["received_quantity"]
    # Validate the whole receipt before committing anything (atomicity)
    parsed = []
    for ln in lines_raw:
        if not isinstance(ln, dict) or not valid_str(ln.get("sku")):
            raise_error(ERR_INVALID_REQUEST, "each received line requires an sku")
        qty = ln.get("received_quantity", ln.get("quantity"))
        if not valid_int(qty) or qty <= 0:
            raise_error(ERR_INVALID_REQUEST, "received quantity must be a positive integer")
        if ln["sku"] not in ordered:
            raise_error(ERR_INVALID_REQUEST, f"sku {ln['sku']} is not on this purchase order")
        parsed.append((ln["sku"], qty))
    requested = {}
    for sku, qty in parsed:
        requested[sku] = requested.get(sku, 0) + qty
    for sku, qty in requested.items():
        if qty > ordered[sku] - already.get(sku, 0):
            raise_error(ERR_INVALID_REQUEST,
                        f"received quantity for {sku} exceeds the open ordered quantity")

    for sku, qty in parsed:
        item = next((i for i in db["stock_items"].values()
                     if i["site_id"] == po["site_id"] and i["sku"] == sku), None)
        if item is not None:
            item["on_hand_quantity"] += qty
            recompute_stock_low(item)
            touch(item)
        merged = False
        for ln in po["received_lines"]:
            if ln["sku"] == sku:
                ln["received_quantity"] += qty
                merged = True
                break
        if not merged:
            po["received_lines"].append({"sku": sku, "received_quantity": qty})

    # Completion across aggregated ordered/received maps
    new_received = dict(already)
    for sku, qty in requested.items():
        new_received[sku] = new_received.get(sku, 0) + qty
    complete = all(new_received.get(sku, 0) >= qty for sku, qty in ordered.items())
    po["status"] = "RECEIVED" if complete else "PARTIALLY_RECEIVED"
    touch(po)
    return success_object(public(po))


@bp.post("/purchase-orders/<rid>/cancel")
def cancel_po(rid):
    authorized(["GeneralManager"])
    po = require_path_resource("purchase_orders", rid)
    if po["status"] not in ("DRAFT", "APPROVED"):
        raise_error(ERR_INVALID_STATE, "only DRAFT or APPROVED orders can be cancelled")
    po["status"] = "CANCELLED"
    touch(po)
    return success_object(public(po))
