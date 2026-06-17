"""Special-order routes (PRD §3.8).

A SpecialOrder branches ORDERED -> {RECEIVED, BACKORDER_CANCELLED}.
Deposit is computed at creation (calc special_order_deposit) and is
non-refundable.
"""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_STATE
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.calculations import special_order_deposit
from services.validation import (
    lookup_fk_or_404,
    lookup_path_or_404,
    require_fields,
    require_int,
    require_string,
)

bp = Blueprint("special_orders", __name__)


@bp.post("/special-orders")
def create_special_order():
    require_auth(["InventoryManager", "ServiceAdvisor"])()
    body = get_json_body()
    require_fields(body, ["work_order_line_id", "tire_model_id", "requested_quantity"])
    work_order_line_id = require_string(body["work_order_line_id"], "work_order_line_id")
    tire_model_id = require_string(body["tire_model_id"], "tire_model_id")
    requested_quantity = require_int(body["requested_quantity"],
                                     "requested_quantity", min_value=1)

    with db.mutation_lock:
        lookup_fk_or_404(db.work_order_lines, work_order_line_id, "WorkOrderLine")
        model = lookup_fk_or_404(db.tire_models, tire_model_id, "TireModel")
        deposit = special_order_deposit(model["unit_price_cents"], requested_quantity)
        so = {
            "work_order_line_id": work_order_line_id,
            "tire_model_id": tire_model_id,
            "requested_quantity": requested_quantity,
            "deposit_cents": deposit,
            "status": "ORDERED",
        }
        db.stamp_common(so)
        db.special_orders[so["id"]] = so
        return ok_object(so, 201)


@bp.get("/special-orders/<sid>")
def get_special_order(sid: str):
    require_auth(["InventoryManager", "ServiceAdvisor"])()
    so = lookup_path_or_404(db.special_orders, sid, "SpecialOrder")
    return ok_object(so, 200)


@bp.get("/special-orders")
def list_special_orders():
    require_auth(["InventoryManager", "ServiceAdvisor"])()
    limit, offset = paginate_params(request.args)
    items = list(db.special_orders.values())
    if "work_order_line_id" in request.args:
        items = [s for s in items
                 if s["work_order_line_id"] == request.args["work_order_line_id"]]
    if "tire_model_id" in request.args:
        items = [s for s in items
                 if s["tire_model_id"] == request.args["tire_model_id"]]
    if "status" in request.args:
        items = [s for s in items if s["status"] == request.args["status"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.post("/special-orders/<sid>/receive")
def receive_special_order(sid: str):
    require_auth(["InventoryManager"])()
    so = lookup_path_or_404(db.special_orders, sid, "SpecialOrder")
    with db.mutation_lock:
        if so["status"] != "ORDERED":
            raise APIError(ERR_INVALID_STATE, 409, "SpecialOrder is not ORDERED")
        model = db.tire_models[so["tire_model_id"]]
        model["stock_qty"] += so["requested_quantity"]
        db.bump(model)
        so["status"] = "RECEIVED"
        db.bump(so)
        return ok_object(so, 200)


@bp.post("/special-orders/<sid>/cancel-backorder")
def cancel_backorder(sid: str):
    require_auth(["InventoryManager"])()
    so = lookup_path_or_404(db.special_orders, sid, "SpecialOrder")
    with db.mutation_lock:
        if so["status"] != "ORDERED":
            raise APIError(ERR_INVALID_STATE, 409, "SpecialOrder is not ORDERED")
        # deposit_cents forfeited — remains booked, unchanged.
        so["status"] = "BACKORDER_CANCELLED"
        db.bump(so)
        # Linked line -> VOID if its parent work order is still DRAFT.
        line = db.work_order_lines.get(so["work_order_line_id"])
        if line is not None and line["line_status"] != "VOID":
            parent = db.work_orders.get(line["work_order_id"])
            if parent is not None and parent["fulfillment_status"] == "DRAFT":
                line["line_status"] = "VOID"
                db.bump(line)
        return ok_object(so, 200)
