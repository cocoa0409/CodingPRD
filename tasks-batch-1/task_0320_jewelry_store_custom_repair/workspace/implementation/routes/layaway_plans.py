"""Layaway plans — reserving, paying down, settling (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.calc import (
    down_payment_cents, installment_amount_cents, restocking_fee_cents, settlement_refund_cents,
)
from services.common import (
    get_body, require_str, require_int, resolve_fk, resolve_path,
    require_own_version, require_item_version, post_ledger_entry,
)

bp = Blueprint("layaway_plans", __name__)


def recompute_paid_to_date(plan):
    """down_payment + sum of SUCCEEDED layaway payments (PRD §3.5)."""
    total = plan.get("down_payment_cents") or 0
    for p in db.payments.values():
        if p["target_type"] == "LAYAWAY" and p.get("layaway_plan_id") == plan["id"] \
                and p["outcome"] == "SUCCEEDED":
            total += p["amount_cents"]
    plan["paid_to_date_cents"] = total
    return total


@bp.route("/layaway-plans", methods=["POST"])
def create_layaway_plan():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    resolve_fk(db.customers, customer_id)
    inventory_item_id = require_str(body, "inventory_item_id")
    resolve_fk(db.inventory_items, inventory_item_id)
    installment_count = require_int(body, "installment_count", minimum=2, maximum=24)
    rec = db.new_record()
    rec.update({
        "customer_id": customer_id, "inventory_item_id": inventory_item_id,
        "item_price_cents": None, "down_payment_cents": None,
        "installment_count": installment_count, "installment_amount_cents": None,
        "paid_to_date_cents": 0, "projected_payoff_cents": None,
        "settlement_refund_cents": None, "restocking_fee_cents": None, "status": "PENDING",
    })
    db.layaway_plans[rec["id"]] = rec
    return success(serialize.layaway_plan(rec), status=201)


@bp.route("/layaway-plans", methods=["GET"])
def list_layaway_plans():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    f_customer = request.args.get("customer_id")
    f_item = request.args.get("inventory_item_id")
    records = []
    for p in db.layaway_plans.values():
        if f_customer is not None and p["customer_id"] != f_customer:
            continue
        if f_item is not None and p["inventory_item_id"] != f_item:
            continue
        records.append(p)
    page, meta = paginate(records, limit, offset)
    return success([serialize.layaway_plan(r) for r in page], status=200, pagination=meta)


@bp.route("/layaway-plans/<pid>", methods=["GET"])
def get_layaway_plan(pid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = resolve_path(db.layaway_plans, pid)
    return success(serialize.layaway_plan(rec), status=200)


@bp.route("/layaway-plans/<pid>/activate", methods=["POST"])
def activate_plan(pid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate"})
    rec = resolve_path(db.layaway_plans, pid)
    body = get_body()
    if rec["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Plan is not PENDING")
    item = db.inventory_items.get(rec["inventory_item_id"])
    # Cross-entity guard: item must be IN_STOCK.
    if item is None or item["status"] != "IN_STOCK":
        raise ApiError("ERR_ITEM_NOT_AVAILABLE", "Inventory item is not IN_STOCK")
    # OCC on the item.
    require_item_version(item, body)
    price = item["list_price_cents"]
    rec["item_price_cents"] = price
    rec["down_payment_cents"] = down_payment_cents(price)
    rec["installment_amount_cents"] = installment_amount_cents(
        price, rec["down_payment_cents"], rec["installment_count"])
    rec["projected_payoff_cents"] = price
    rec["paid_to_date_cents"] = rec["down_payment_cents"]
    rec["status"] = "ACTIVE"
    db.touch(rec)
    item["status"] = "RESERVED"
    db.touch(item)
    return success(serialize.layaway_plan(rec), status=200)


@bp.route("/layaway-plans/<pid>/fulfill", methods=["POST"])
def fulfill_plan(pid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate"})
    rec = resolve_path(db.layaway_plans, pid)
    body = get_body()
    if rec["status"] != "PAID_IN_FULL":
        raise ApiError("ERR_INVALID_STATE", "Plan is not PAID_IN_FULL")
    require_own_version(rec, body)
    rec["status"] = "FULFILLED"
    db.touch(rec)
    item = db.inventory_items.get(rec["inventory_item_id"])
    if item is not None:
        item["status"] = "SOLD"
        db.touch(item)
    return success(serialize.layaway_plan(rec), status=200)


@bp.route("/layaway-plans/<pid>/cancel", methods=["POST"])
def cancel_plan(pid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.layaway_plans, pid)
    body = get_body()
    if rec["status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", "Plan cannot be cancelled from its current state")
    require_own_version(rec, body)
    was_active = rec["status"] == "ACTIVE"
    # Settlement. Pre-activation, item_price/paid_to_date are unset -> treat as 0.
    price = rec.get("item_price_cents") or 0
    paid = rec.get("paid_to_date_cents") or 0
    fee = restocking_fee_cents(price) if price > 0 else 0
    refund = settlement_refund_cents(paid, fee)
    rec["restocking_fee_cents"] = fee
    rec["settlement_refund_cents"] = refund
    rec["status"] = "CANCELLED"
    db.touch(rec)
    if was_active:
        item = db.inventory_items.get(rec["inventory_item_id"])
        if item is not None:
            item["status"] = "IN_STOCK"
            db.touch(item)
    if refund > 0:
        post_ledger_entry(rec["customer_id"], "CREDIT", refund, "LAYAWAY_REFUND")
    return success(serialize.layaway_plan(rec), status=200)
