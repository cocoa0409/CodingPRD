"""Layaway routes: create, post installment, cancel, lists (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, parse_iso
from errors import err
from middleware import require_auth
from models import base_record, event_record, touch
from helpers import (
    get_body,
    as_str,
    as_int,
    parse_pagination,
    paginate,
    sort_by_creation,
    serialize,
)
from response import success_object, success_array
from services import calc
from services.domain import schedule_for_state, active_hold_on_inventory_item

bp = Blueprint("layaway", __name__)


def _drawer_for_shop(shop_id):
    for d in store.cash_drawers.values():
        if d["shop_id"] == shop_id:
            return d
    return None


def _installments_for_plan(plan_id):
    rows = [i for i in store.layaway_installments.values() if i["layaway_plan_id"] == plan_id]
    return sorted(rows, key=lambda r: r["sequence"])


# ---------------------------------------------------------------------------
# Create a layaway plan (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.route("/pawn/layaway-plans", methods=["POST"])
def create_layaway():
    require_auth(["ShopManager"])
    body = get_body()

    inventory_item_id = as_str(body, "inventory_item_id")
    customer_id = as_str(body, "customer_id")
    installment_count = as_int(body, "installment_count")
    reserved_until_raw = as_str(body, "reserved_until_at")

    # Existence (priority 3).
    inv = store.inventory_items.get(inventory_item_id)
    if inv is None:
        raise err("ERR_NOT_FOUND", "Inventory item not found.")
    if customer_id not in store.customers:
        raise err("ERR_NOT_FOUND", "Customer not found.")

    # Well-formedness (priority 4).
    if installment_count < 1 or installment_count > 12:
        raise err("ERR_INVALID_REQUEST", "installment_count must be between 1 and 12.")
    reserved_until_at = parse_iso(reserved_until_raw)
    if reserved_until_at is None:
        raise err("ERR_INVALID_REQUEST", "reserved_until_at is not a valid ISO 8601 timestamp.")

    reserved_from_at = store.now()
    if not (reserved_until_at > reserved_from_at):
        raise err("ERR_INVALID_REQUEST", "reserved_until_at must be after reserved_from_at.")

    # State (priority 5): item must be AVAILABLE.
    if inv["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Inventory item is not AVAILABLE.")

    # Police hold (priority 7).
    if active_hold_on_inventory_item(inventory_item_id) is not None:
        raise err("ERR_POLICE_HOLD_ACTIVE", "An active police hold names this item.")

    # Reservation cool-down conflict (priority 14): reserved_from_at must be
    # at/after last_layaway_end_at + layaway_buffer_days (buffer endpoint inclusive).
    if inv["last_layaway_end_at"] is not None:
        shop = store.shops.get(inv["shop_id"])
        schedule = schedule_for_state(shop["state_code"]) if shop else None
        buffer_days = schedule["layaway_buffer_days"] if schedule else 0
        buffered = inv["last_layaway_end_at"] + timedelta(days=buffer_days)
        if reserved_from_at < buffered:
            raise err(
                "ERR_LAYAWAY_RESERVATION_CONFLICT",
                "Reservation starts within the restock cool-down buffer.",
            )

    # Snapshot total price and build the schedule.
    total_price = inv["list_price_cents"]
    deposit, amounts = calc.layaway_installments(total_price, installment_count)

    plan = base_record({
        "inventory_item_id": inventory_item_id,
        "customer_id": customer_id,
        "total_price_cents": total_price,
        "deposit_cents": deposit,
        "installment_count": installment_count,
        "reserved_from_at": reserved_from_at,
        "reserved_until_at": reserved_until_at,
        "paid_cents": deposit,
        "status": "ACTIVE",
    })
    store.layaway_plans[plan["id"]] = plan

    for seq, amt in enumerate(amounts, start=1):
        row = event_record({
            "layaway_plan_id": plan["id"],
            "sequence": seq,
            "amount_cents": amt,
            "paid": False,
        })
        store.layaway_installments[row["id"]] = row

    # Move the inventory item to ON_LAYAWAY; collect the deposit.
    inv["status"] = "ON_LAYAWAY"
    touch(inv)
    drawer = _drawer_for_shop(inv["shop_id"])
    if drawer is not None:
        drawer["balance_cents"] += deposit
        touch(drawer)

    return success_object(serialize(plan), 201)


@bp.route("/pawn/layaway-plans/<plan_id>", methods=["GET"])
def get_layaway(plan_id):
    require_auth(["ShopManager", "LoanOfficer"])
    plan = store.layaway_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Layaway plan not found.")
    return success_object(serialize(plan))


@bp.route("/pawn/layaway-plans", methods=["GET"])
def list_layaway():
    require_auth(["ShopManager", "LoanOfficer"])
    limit, offset = parse_pagination()
    inventory_item_id = request.args.get("inventory_item_id")
    customer_id = request.args.get("customer_id")
    items = list(store.layaway_plans.values())
    if inventory_item_id is not None:
        items = [p for p in items if p["inventory_item_id"] == inventory_item_id]
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(p) for p in window], limit, offset, total)


@bp.route("/pawn/layaway-plans/<plan_id>/installments", methods=["GET"])
def list_installments(plan_id):
    require_auth(["ShopManager", "LoanOfficer"])
    plan = store.layaway_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Layaway plan not found.")
    limit, offset = parse_pagination()
    items = _installments_for_plan(plan_id)
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(i) for i in window], limit, offset, total)


@bp.route("/pawn/layaway-plans/<plan_id>/installments", methods=["POST"])
def post_installment(plan_id):
    require_auth(["ShopManager"])
    plan = store.layaway_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Layaway plan not found.")

    body = get_body()
    amount_cents = as_int(body, "amount_cents")

    # State (priority 5): plan must be ACTIVE.
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Layaway plan is not ACTIVE.")

    # Next unpaid scheduled installment.
    rows = _installments_for_plan(plan_id)
    next_unpaid = None
    for r in rows:
        if not r["paid"]:
            next_unpaid = r
            break

    # Installment mismatch / exhausted schedule (priority 15).
    if next_unpaid is None:
        raise err("ERR_INSTALLMENT_MISMATCH", "No unpaid installment remains.")
    if amount_cents != next_unpaid["amount_cents"]:
        raise err("ERR_INSTALLMENT_MISMATCH", "Amount does not match the scheduled installment.")

    next_unpaid["paid"] = True
    plan["paid_cents"] += amount_cents
    drawer = _drawer_for_shop(_shop_for_plan(plan))
    if drawer is not None:
        drawer["balance_cents"] += amount_cents
        touch(drawer)

    # If this was the final installment (paid_cents == total_price), complete & auto-sell.
    if plan["paid_cents"] == plan["total_price_cents"]:
        plan["status"] = "COMPLETED"
        inv = store.inventory_items.get(plan["inventory_item_id"])
        if inv is not None:
            inv["status"] = "SOLD"
            inv["sold_price_cents"] = plan["total_price_cents"]
            touch(inv)
    touch(plan)
    return success_object(serialize(plan))


@bp.route("/pawn/layaway-plans/<plan_id>/cancel", methods=["POST"])
def cancel_layaway(plan_id):
    require_auth(["ShopManager"])
    plan = store.layaway_plans.get(plan_id)
    if plan is None:
        raise err("ERR_NOT_FOUND", "Layaway plan not found.")

    # State (priority 5): plan must be ACTIVE.
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Layaway plan is not ACTIVE.")

    plan["status"] = "DEFAULTED"
    inv = store.inventory_items.get(plan["inventory_item_id"])
    if inv is not None:
        inv["status"] = "AVAILABLE"
        inv["last_layaway_end_at"] = store.now()
        touch(inv)

    refund = calc.layaway_refund(plan["total_price_cents"], plan["paid_cents"])
    drawer = _drawer_for_shop(_shop_for_plan(plan))
    if drawer is not None and refund:
        drawer["balance_cents"] -= refund
        touch(drawer)

    touch(plan)
    return success_object(serialize(plan))


def _shop_for_plan(plan):
    inv = store.inventory_items.get(plan["inventory_item_id"])
    return inv["shop_id"] if inv is not None else None
