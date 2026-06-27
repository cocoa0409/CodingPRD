"""SalesOrder + SalesOrderLine endpoints + sales lifecycle (PRD §3.10)."""
from decimal import Decimal

from flask import Blueprint, request

import errors
import serializers
import calculations
from common import (stamp_create, touch, get_body, require_str, require_number,
                    require_int, optional_enum, must_get, require_fk, paginate,
                    D, round2)
from db import store
from middleware import require_roles
from response import object_response, array_response
from domain import recompute_lot_weights

bp = Blueprint("sales", __name__)

DISCOUNT_TIERS = {"NONE", "BRONZE", "SILVER", "GOLD"}
SALES_READ_ROLES = {"FarmManager", "SalesAgent"}


def _order_lines(order_id):
    lines = [l for l in store.sales_order_lines.values() if l["sales_order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


# ===========================================================================
# SalesOrder
# ===========================================================================
@bp.route("/sales-orders", methods=["POST"])
def create_sales_order():
    require_roles({"SalesAgent"})
    body = get_body()
    customer_name = require_str(body, "customer_name")
    discount_tier = optional_enum(body, "discount_tier", DISCOUNT_TIERS, default="NONE")
    with store.lock:
        rec = {
            "customer_name": customer_name,
            "discount_tier": discount_tier,
            "order_total": 0,
            "status": "DRAFT",
        }
        stamp_create(rec)
        store.sales_orders[rec["id"]] = rec
        data = serializers.sales_order_out(rec)
    return object_response(data, 201)


@bp.route("/sales-orders", methods=["GET"])
def list_sales_orders():
    require_roles(SALES_READ_ROLES)
    status = request.args.get("status")
    with store.lock:
        items = list(store.sales_orders.values())
        if status is not None:
            items = [o for o in items if o["status"] == status]
        window, limit, offset, total = paginate(items)
        data = [serializers.sales_order_out(o) for o in window]
    return array_response(data, limit, offset, total)


@bp.route("/sales-orders/<oid>", methods=["GET"])
def get_sales_order(oid):
    require_roles(SALES_READ_ROLES)
    with store.lock:
        rec = must_get(store.sales_orders, oid)
        data = serializers.sales_order_out(rec)
    return object_response(data, 200)


@bp.route("/sales-orders/<oid>/lines", methods=["POST"])
def add_line(oid):
    require_roles({"SalesAgent"})
    with store.lock:
        order = must_get(store.sales_orders, oid)
        if order["status"] != "DRAFT":
            raise errors.invalid_state()
        body = get_body()
        lot_id, lot = require_fk(body, "product_lot_id", store.product_lots)
        weight = require_number(body, "weight_kg", gt=0)

        # No two lines on the same order may reference the same lot (PRD §3.10).
        for existing in store.sales_order_lines.values():
            if existing["sales_order_id"] == oid and existing["product_lot_id"] == lot_id:
                raise errors.duplicate_line_lot()

        line = {
            "sales_order_id": oid,
            "product_lot_id": lot_id,
            "weight_kg": weight,
            "line_subtotal": calculations.line_subtotal(weight, lot["price_per_kg"]),
        }
        stamp_create(line)
        store.sales_order_lines[line["id"]] = line
        data = serializers.sales_order_line_out(line)
    return object_response(data, 201)


@bp.route("/sales-order-lines", methods=["GET"])
def list_lines():
    require_roles(SALES_READ_ROLES)
    sales_order_id = request.args.get("sales_order_id")
    product_lot_id = request.args.get("product_lot_id")
    with store.lock:
        items = list(store.sales_order_lines.values())
        if sales_order_id is not None:
            items = [l for l in items if l["sales_order_id"] == sales_order_id]
        if product_lot_id is not None:
            items = [l for l in items if l["product_lot_id"] == product_lot_id]
        window, limit, offset, total = paginate(items)
        data = [serializers.sales_order_line_out(l) for l in window]
    return array_response(data, limit, offset, total)


@bp.route("/sales-order-lines/<lid>", methods=["GET"])
def get_line(lid):
    require_roles(SALES_READ_ROLES)
    with store.lock:
        rec = must_get(store.sales_order_lines, lid)
        data = serializers.sales_order_line_out(rec)
    return object_response(data, 200)


@bp.route("/sales-orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    require_roles({"SalesAgent"})
    with store.lock:
        order = must_get(store.sales_orders, oid)
        body = get_body()
        expected_lot_version = require_int(body, "expected_lot_version")

        if order["status"] != "DRAFT":
            raise errors.invalid_state()

        lines = _order_lines(oid)
        # Empty order (PRD §3.10). EMPTY_ORDER is a business rule (422); per §2.12
        # business rules follow the state/OCC gates, but with zero lines there is
        # no lot to OCC-check, so an empty order is rejected here.
        if not lines:
            raise errors.empty_order()

        # Resolve referenced lots.
        lot_ids = []
        for l in lines:
            if l["product_lot_id"] not in lot_ids:
                lot_ids.append(l["product_lot_id"])
        lots = {lid: store.product_lots[lid] for lid in lot_ids if lid in store.product_lots}

        # OCC (PRD §2.8, priority 5): every referenced lot's version must equal
        # expected_lot_version.
        for lid in lot_ids:
            lot = lots.get(lid)
            if lot is None:
                raise errors.not_found()
            if lot["version"] != expected_lot_version:
                raise errors.stale_version()

        # Lot integrity (PRD §3.10, priority 11): every referenced lot AVAILABLE.
        for lid in lot_ids:
            if lots[lid]["status"] == "DEPLETED":
                raise errors.lot_depleted()

        # Availability / quota (priority 12): per-line and aggregate per lot.
        agg = {}
        for l in lines:
            agg[l["product_lot_id"]] = agg.get(l["product_lot_id"], D(0)) + D(l["weight_kg"])
        for lid, total_req in agg.items():
            if total_req > D(lots[lid]["available_weight_kg"]):
                raise errors.insufficient_lot_weight()

        # Compute order total (PRD §3.10 pinned rounding).
        lines_with_lots = [(l, lots[l["product_lot_id"]]) for l in lines]
        order["order_total"] = calculations.compute_order_total(
            lines_with_lots, order["discount_tier"])

        # Reserve: per lot, reserved += line weight; recompute available; DEPLETED
        # at exactly 0. Each referenced lot's version bumps.
        for lid, added in agg.items():
            lot = lots[lid]
            lot["reserved_weight_kg"] = round2(D(lot["reserved_weight_kg"]) + added)
            recompute_lot_weights(lot)
            touch(lot)

        order["status"] = "CONFIRMED"
        touch(order)
        data = serializers.sales_order_out(order)
    return object_response(data, 200)


@bp.route("/sales-orders/<oid>/fulfill", methods=["POST"])
def fulfill_order(oid):
    require_roles({"SalesAgent"})
    with store.lock:
        order = must_get(store.sales_orders, oid)
        if order["status"] != "CONFIRMED":
            raise errors.invalid_state()

        lines = _order_lines(oid)
        agg = {}
        for l in lines:
            agg[l["product_lot_id"]] = agg.get(l["product_lot_id"], D(0)) + D(l["weight_kg"])
        for lid, amount in agg.items():
            lot = store.product_lots.get(lid)
            if lot is None:
                continue
            lot["reserved_weight_kg"] = round2(D(lot["reserved_weight_kg"]) - amount)
            lot["shipped_weight_kg"] = round2(D(lot["shipped_weight_kg"]) + amount)
            recompute_lot_weights(lot)
            touch(lot)

        order["status"] = "FULFILLED"
        touch(order)
        data = serializers.sales_order_out(order)
    return object_response(data, 200)


@bp.route("/sales-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    require_roles({"SalesAgent"})
    with store.lock:
        order = must_get(store.sales_orders, oid)
        if order["status"] != "CONFIRMED":
            raise errors.invalid_state()

        # Cascade hop 1: order CANCELLED.
        order["status"] = "CANCELLED"

        # Cascade hop 2: release reserved per lot; recompute available upward.
        # Hop 2b: DEPLETED lots with available > 0 revert to AVAILABLE (handled by
        # recompute_lot_weights which derives status from available).
        lines = _order_lines(oid)
        agg = {}
        for l in lines:
            agg[l["product_lot_id"]] = agg.get(l["product_lot_id"], D(0)) + D(l["weight_kg"])
        for lid, amount in agg.items():
            lot = store.product_lots.get(lid)
            if lot is None:
                continue
            lot["reserved_weight_kg"] = round2(D(lot["reserved_weight_kg"]) - amount)
            recompute_lot_weights(lot)
            touch(lot)

        touch(order)
        data = serializers.sales_order_out(order)
    return object_response(data, 200)
