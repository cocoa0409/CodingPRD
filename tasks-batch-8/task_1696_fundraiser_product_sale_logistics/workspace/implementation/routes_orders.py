"""Order endpoints: create (with inline lines + idempotency), submit, cancel, lists."""

import json

from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import services
from db import clock, _parse_iso
from helpers import (
    get_campaign, get_order, get_product, get_seller, new_id, now_iso,
    paginate, sort_created,
    req_string, opt_string,
    serialize_order, serialize_order_line, serialize_payment,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("orders", __name__)


def _fingerprint(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@bp.post("/fundraiser/orders")
def create_order():
    middleware.require_role("GroupCoordinator")
    body = get_body(required=True)
    # --- Schema validation (priority 4) ---
    seller_id = req_string(body, "seller_id")
    family_contact_name = req_string(body, "family_contact_name")
    idempotency_key = opt_string(body, "idempotency_key", default=None)
    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise errors.err_validation("lines must be a non-empty array")
    parsed_lines = []
    for item in lines:
        if not isinstance(item, dict):
            raise errors.err_validation("each line must be an object")
        pid = item.get("product_id")
        if not isinstance(pid, str) or pid == "":
            raise errors.err_validation("line.product_id is required")
        qty = item.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise errors.err_validation("line.quantity must be an integer >= 1")
        parsed_lines.append((pid, qty))

    # --- Idempotency replay (priority 5), scoped to endpoint+seller ---
    scope = ("POST /fundraiser/orders", seller_id)
    if idempotency_key is not None:
        record = db.idempotency_records.get((scope, idempotency_key))
        if record is not None:
            fp, status, body_json = record
            if fp != _fingerprint(body):
                raise errors.err_idempotency_conflict()
            from flask import Response
            return Response(body_json, status=status, content_type="application/json")

    # --- Body FK resolution (priority 6) ---
    seller = get_seller(seller_id)
    for (pid, _qty) in parsed_lines:
        get_product(pid)

    # --- State gates (priority 8): campaign OPEN; seller not WITHDRAWN/SUSPENDED ---
    campaign = get_campaign(seller["campaign_id"])
    if campaign["status"] != "OPEN":
        raise errors.err_campaign_not_open()
    if seller["status"] == "WITHDRAWN":
        raise errors.err_invalid_state("Seller is WITHDRAWN")
    if seller["status"] == "SUSPENDED":
        raise errors.err_seller_suspended()

    oid = new_id()
    order = {
        "id": oid,
        "seller_id": seller_id,
        "campaign_id": seller["campaign_id"],
        "group_id": seller["group_id"],
        "family_contact_name": family_contact_name,
        "status": "DRAFT",
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
        "total_cents": 0,
        "cleared_cents": 0,
        "provisional_credit_cents": 0,
        "submitted_at": None,
        "idempotency_key": idempotency_key,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.orders[oid] = order
    for (pid, qty) in parsed_lines:
        lid = new_id()
        db.order_lines[lid] = {
            "id": lid,
            "order_id": oid,
            "product_id": pid,
            "quantity": qty,
            "unit_price_cents": None,
            "unit_cost_cents": None,
            "line_total_cents": None,
            "returned_qty": 0,
            "claim_resolved_refund_qty": 0,
            "sort_shortage_qty": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "version": 1,
        }

    resp, status = success_object(serialize_order(order), status=201)
    if idempotency_key is not None:
        db.idempotency_records[(scope, idempotency_key)] = (
            _fingerprint(body), status, resp.get_data(as_text=True),
        )
    return resp, status


@bp.get("/fundraiser/orders")
def list_orders():
    middleware.any_role()
    limit, offset = parse_pagination()
    items = list(db.orders.values())
    for param in ("seller_id", "campaign_id", "group_id", "status", "payment_status", "fulfillment_status"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o.get(param) == v]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_order(o) for o in page], limit, offset, total)


@bp.get("/fundraiser/orders/<oid>")
def read_order(oid):
    middleware.any_role()
    order = get_order(oid)
    return success_object(serialize_order(order))


@bp.post("/fundraiser/orders/<oid>/submit")
def submit_order(oid):
    middleware.require_role("GroupCoordinator")
    order = get_order(oid)
    get_body()
    if order["status"] != "DRAFT":
        raise errors.err_invalid_state("Order is not DRAFT")
    campaign = get_campaign(order["campaign_id"])
    if campaign["status"] != "OPEN":
        raise errors.err_campaign_not_open()
    now = clock.now()
    if not (_parse_iso(campaign["order_window_start"]) <= now <= _parse_iso(campaign["order_window_end"])):
        raise errors.err_outside_order_window()
    seller = get_seller(order["seller_id"])
    if seller["status"] == "SUSPENDED":
        raise errors.err_seller_suspended()
    if seller["status"] not in ("ENROLLED", "ACTIVE"):
        raise errors.err_invalid_state("Seller is WITHDRAWN")
    lines = [ln for ln in db.order_lines.values() if ln["order_id"] == oid]
    if not lines:
        raise errors.err_validation("Order has no lines")
    for ln in lines:
        product = get_product(ln["product_id"])
        if product["status"] != "ACTIVE":
            raise errors.err_product_not_orderable()
    # Per-seller cumulative limit check, including the submitting order
    for ln in lines:
        product = get_product(ln["product_id"])
        limit = product["per_seller_limit"]
        if limit is None:
            continue
        cumulative = 0
        for o in db.orders.values():
            if o["seller_id"] == seller["id"] and o["status"] != "CANCELLED":
                for other in db.order_lines.values():
                    if other["order_id"] == o["id"] and other["product_id"] == ln["product_id"]:
                        cumulative += other["quantity"]
        if cumulative > limit:
            raise errors.err_per_seller_limit_exceeded()

    # Snapshot prices/costs, compute totals
    total = 0
    for ln in lines:
        product = db.products[ln["product_id"]]
        ln["unit_price_cents"] = product["unit_price_cents"]
        ln["unit_cost_cents"] = product["supplier_unit_cost_cents"]
        ln["line_total_cents"] = ln["quantity"] * product["unit_price_cents"]
        helpers.touch(ln)
        total += ln["line_total_cents"]
    order["total_cents"] = total
    order["submitted_at"] = now_iso()
    order["status"] = "SUBMITTED"

    # Provisional proceeds credit (per-line round_half_up, summed per order)
    from decimal import Decimal
    credit_total = 0
    for ln in lines:
        product = db.products[ln["product_id"]]
        line_net = ln["line_total_cents"] - ln["quantity"] * ln["unit_cost_cents"]
        share = (Decimal(line_net) * Decimal(product["profit_share_bps"])) / Decimal(10000)
        credit_total += services.round_half_up_cents(share)
    order["provisional_credit_cents"] = credit_total
    helpers.touch(order)
    services.post_ledger_entry(
        group_id=order["group_id"], campaign_id=order["campaign_id"],
        entry_type="PROVISIONAL_CREDIT", amount_cents=credit_total,
        reference_type="ORDER", reference_id=order["id"],
        memo=f"Provisional proceeds credit for order {order['id']}",
    )
    group = db.groups[order["group_id"]]
    group["provisional_proceeds_cents"] = services.recompute_group_provisional(order["group_id"])
    helpers.touch(group)

    if seller["status"] == "ENROLLED":
        seller["status"] = "ACTIVE"
        helpers.touch(seller)
    services.recompute_seller_metrics(seller)
    services.evaluate_prizes_for_seller(seller)
    services.recompute_campaign_totals(campaign)
    return success_object(serialize_order(order))


@bp.post("/fundraiser/orders/<oid>/cancel")
def cancel_order_route(oid):
    middleware.require_role("GroupCoordinator")
    order = get_order(oid)
    get_body()
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        raise errors.err_invalid_state("Order cannot be cancelled from its current state")
    if order["status"] == "SUBMITTED":
        if order["cleared_cents"] != 0:
            raise errors.err_order_has_cleared_payments()
        campaign = get_campaign(order["campaign_id"])
        if campaign["status"] not in ("OPEN", "ORDERING_CLOSED"):
            raise errors.err_invalid_state("Campaign state does not permit cancellation")
        services.cancel_order(order, post_reversal=True)
        group = db.groups[order["group_id"]]
        group["provisional_proceeds_cents"] = services.recompute_group_provisional(order["group_id"])
        helpers.touch(group)
    else:
        order["status"] = "CANCELLED"
        helpers.touch(order)
        services.recompute_campaign_totals(db.campaigns[order["campaign_id"]])
    return success_object(serialize_order(order))


@bp.get("/fundraiser/orders/<oid>/lines")
def list_order_lines(oid):
    middleware.any_role()
    get_order(oid)
    limit, offset = parse_pagination()
    items = sort_created([ln for ln in db.order_lines.values() if ln["order_id"] == oid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_order_line(ln) for ln in page], limit, offset, total)


@bp.get("/fundraiser/orders/<oid>/payments")
def list_order_payments(oid):
    middleware.any_role()
    get_order(oid)
    limit, offset = parse_pagination()
    items = sort_created([p for p in db.payments.values() if p["order_id"] == oid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_payment(p) for p in page], limit, offset, total)
