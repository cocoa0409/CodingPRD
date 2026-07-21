"""Orders, order-lines, and order lifecycle (quote / confirm / cancel / payments)."""
from flask import Blueprint

import serializers
import services
from auth import require, check_designer_ownership
from envelope import ok, created
from errors import err
from listing import list_response
from store import db, new_base, insert, touch, fetch, fk
from validation import get_body, req_str, req_int, req_enum, req_str_list

bp = Blueprint("orders", __name__)

GET_ALL = ("ShowroomAssociate", "StoreManager", "Designer", "FulfillmentCoordinator")


# --------------------------- Order CRUD ---------------------------
@bp.post("/orders")
@require("ShowroomAssociate", "StoreManager", "Designer")
def create_order():
    body = get_body()
    # FK existence (before structural body validity)
    trade_account_id = body.get("trade_account_id")
    if trade_account_id is not None:
        fk("trade_accounts", trade_account_id)
    customer_name = req_str(body, "customer_name")
    # Designer ownership-and-active guard (last business check)
    check_designer_ownership(trade_account_id)
    rec = new_base()
    rec.update(
        {
            "trade_account_id": trade_account_id,
            "customer_name": customer_name,
            "fulfillment_status": "DRAFT",
            "payment_status": "UNPAID",
            "subtotal_estimate_cents": 0,
            "discount_estimate_cents": 0,
            "total_estimate_cents": 0,
            "subtotal_final_cents": None,
            "discount_final_cents": None,
            "total_final_cents": None,
            "committed_credit_cents": 0,
            "amount_paid_cents": 0,
            "settled_at": None,
        }
    )
    insert("orders", rec)
    return created(serializers.order(rec))


@bp.get("/orders/<rec_id>")
@require(*GET_ALL)
def get_order(rec_id):
    return ok(serializers.order(fetch("orders", rec_id)))


@bp.get("/orders")
@require(*GET_ALL)
def list_orders():
    return list_response(
        db.orders.values(), serializers.order, {"trade_account_id": "trade_account_id"}
    )


# --------------------------- Order lines ---------------------------
@bp.post("/orders/<rec_id>/lines")
@require("ShowroomAssociate", "StoreManager", "Designer")
def add_line(rec_id):
    order = fetch("orders", rec_id)
    body = get_body()
    fixture_model_id = body.get("fixture_model_id")
    if fixture_model_id is None:
        raise err("ERR_INVALID_REQUEST", "fixture_model_id is required")
    fixture = fk("fixture_models", fixture_model_id)
    quantity = req_int(body, "quantity")
    if quantity < 1:
        raise err("ERR_INVALID_REQUEST", "quantity must be >= 1")
    selected = req_str_list(body, "selected_option_ids", [])
    valid_ids = {o["option_id"] for o in fixture.get("options", [])}
    for oid in selected:
        if oid not in valid_ids:
            raise err("ERR_INVALID_REQUEST", "selected_option_ids must all belong to the fixture")
    # state guard
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_DRAFT", "Lines may be added only to a DRAFT order")
    # ownership (last)
    check_designer_ownership(order.get("trade_account_id"))

    selected_set = set(selected)
    suffix = "".join(
        o["sku_suffix"] for o in fixture.get("options", []) if o["option_id"] in selected_set
    )
    configured_sku = fixture["sku_base"] + suffix
    unit_price = fixture["base_price_cents"] + sum(
        o["price_delta_cents"] for o in fixture.get("options", []) if o["option_id"] in selected_set
    )
    line = new_base()
    line.update(
        {
            "order_id": order["id"],
            "fixture_model_id": fixture_model_id,
            "selected_option_ids": selected,
            "configured_sku": configured_sku,
            "quantity": quantity,
            "unit_price_cents": unit_price,
            "is_special_order": fixture["special_order_only"],
            "line_status": "ACTIVE",
        }
    )
    insert("order_lines", line)
    touch(order)  # adding a line mutates the order (§2.6)
    return created(serializers.order_line(line))


@bp.get("/order-lines/<rec_id>")
@require(*GET_ALL)
def get_order_line(rec_id):
    return ok(serializers.order_line(fetch("order_lines", rec_id)))


@bp.get("/order-lines")
@require(*GET_ALL)
def list_order_lines():
    return list_response(
        db.order_lines.values(),
        serializers.order_line,
        {"order_id": "order_id", "fixture_model_id": "fixture_model_id"},
    )


# --------------------------- Quote ---------------------------
@bp.post("/orders/<rec_id>/quote")
@require("ShowroomAssociate", "StoreManager", "Designer")
def quote_order(rec_id):
    order = fetch("orders", rec_id)
    body = get_body()
    expected = req_int(body, "expected_order_version")
    # OCC (before state guard, §2.8)
    if expected != order["version"]:
        raise err("ERR_STALE_VERSION", "expected_order_version does not match current version")
    if order["fulfillment_status"] not in ("DRAFT", "QUOTED"):
        raise err("ERR_INVALID_STATE", "Order cannot be quoted from its current state")
    check_designer_ownership(order.get("trade_account_id"))
    services.compute_order_pricing(order, "ESTIMATE")
    order["fulfillment_status"] = "QUOTED"
    touch(order)
    return ok(serializers.order(order))


# --------------------------- Confirm ---------------------------
@bp.post("/orders/<rec_id>/confirm")
@require("ShowroomAssociate", "StoreManager", "Designer")
def confirm_order(rec_id):
    order = fetch("orders", rec_id)
    if order["fulfillment_status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Only a QUOTED order can be confirmed")
    acct = None
    if order.get("trade_account_id"):
        acct = db.trade_accounts.get(order["trade_account_id"])
        if acct is not None:
            available = services.account_available_credit(acct)
            if available < order["total_estimate_cents"]:
                raise err("ERR_INSUFFICIENT_CREDIT", "Available credit is insufficient")
    check_designer_ownership(order.get("trade_account_id"))
    order["committed_credit_cents"] = order["total_estimate_cents"]
    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    if acct is not None:
        touch(acct)  # available_credit shifts (§2.4)
    return ok(serializers.order(order))


# --------------------------- Cancel ---------------------------
@bp.post("/orders/<rec_id>/cancel")
@require("ShowroomAssociate", "StoreManager")
def cancel_order_route(rec_id):
    order = fetch("orders", rec_id)
    if order["fulfillment_status"] not in ("DRAFT", "QUOTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    services.cancel_order(order)
    return ok(serializers.order(order))


# --------------------------- Payments ---------------------------
@bp.post("/orders/<rec_id>/payments")
@require("ShowroomAssociate", "StoreManager")
def record_payment(rec_id):
    order = fetch("orders", rec_id)
    body = get_body()
    kind = req_enum(body, "kind", {"DEPOSIT", "SETTLEMENT"})
    amount = req_int(body, "amount_cents")
    if kind == "DEPOSIT":
        if order["payment_status"] != "UNPAID" or order["fulfillment_status"] not in (
            "QUOTED",
            "CONFIRMED",
        ):
            raise err("ERR_INVALID_STATE", "Deposit not permitted in current state")
        order["amount_paid_cents"] += amount
        order["payment_status"] = "DEPOSIT_PAID"
        touch(order)
    else:  # SETTLEMENT
        if order["payment_status"] not in ("UNPAID", "DEPOSIT_PAID") or order[
            "fulfillment_status"
        ] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "Settlement not permitted in current state")
        services.compute_order_pricing(order, "FINAL")
        order["amount_paid_cents"] += amount
        order["settled_at"] = db.clock
        order["payment_status"] = "SETTLED"
        touch(order)
        if order.get("trade_account_id"):
            acct = db.trade_accounts.get(order["trade_account_id"])
            if acct is not None:
                touch(acct)  # annual_spend / tier recomputed post-settlement
    return ok(serializers.order(order))
