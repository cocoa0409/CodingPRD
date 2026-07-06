"""Admin-only test-driving capabilities (§3.12)."""
from flask import Blueprint

from db import db, parse_iso
from errors import err
from helpers import body, require_fields, require_str, require_int, get_or_404, fk_or_404
from middleware import get_auth, require_roles
from response import success
from serializers import serialize
from services import pricing
from services.queue import recompute_queue_status

bp = Blueprint("testdrive", __name__)

NON_TERMINAL_ORDER = {"CART", "PLACED", "PREPARING", "READY"}


@bp.post("/_inject/place_n_orders")
def inject_place_n():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["store_id", "menu_item_id", "pickup_slot_id", "count"])
    require_str(data, "store_id")
    require_str(data, "menu_item_id")
    require_str(data, "pickup_slot_id")
    require_int(data, "count")
    store = fk_or_404("store", data["store_id"])
    menu_item = fk_or_404("menu_item", data["menu_item_id"])
    slot = fk_or_404("pickup_slot", data["pickup_slot_id"])
    count = data["count"]
    if count < 0:
        raise err("ERR_INVALID_REQUEST", "count must be >= 0.")

    for i in range(count):
        # capacity gate (strict <)
        if slot["reserved_count"] >= store["throughput_capacity_per_slot"]:
            raise err("ERR_SLOT_CAPACITY_EXCEEDED", "Slot at capacity.")
        # locker gate
        if slot["channel"] == "LOCKER":
            non_terminal_locker = 0
            for o in db.orders.values():
                if (o["store_id"] == store["id"] and o["channel"] == "LOCKER"
                        and o["order_status"] in NON_TERMINAL_ORDER):
                    non_terminal_locker += 1
            if non_terminal_locker >= store["locker_count"]:
                raise err("ERR_NO_LOCKER_AVAILABLE", "No locker available.")

        # distinct fresh customer + loyalty account
        customer = db.common_fields()
        customer.update({
            "email": f"_inject_{customer['id']}@example.com",
            "full_name": "Injected Customer",
            "home_store_id": store["id"],
            "allergen_blocklist": [],
            "wallet_credit_cents": 0,
            "loyalty_account_id": None,
        })
        acct = db.common_fields()
        acct.update({
            "customer_id": customer["id"], "points_balance": 0,
            "lifetime_points_earned": 0, "tier": "GREEN",
        })
        db.loyalty_accounts[acct["id"]] = acct
        customer["loyalty_account_id"] = acct["id"]
        db.customers[customer["id"]] = customer

        order = db.common_fields()
        line_total, line_cal, tags = pricing.compute_line(menu_item, [], 1)
        order.update({
            "customer_id": customer["id"], "store_id": store["id"],
            "pickup_slot_id": slot["id"], "subscription_id": None,
            "channel": slot["channel"], "order_status": "PLACED",
            "settlement_status": "CAPTURED",
            "subtotal_cents": line_total, "delivery_fee_cents": 0,
            "points_redeemed": 0, "discount_cents": 0, "wallet_applied_cents": 0,
            "total_cents": line_total, "total_calories": line_cal,
            "points_earned": 0, "refunded_cents": 0,
        })
        db.orders[order["id"]] = order

        line = db.common_fields()
        line.update({
            "order_id": order["id"], "menu_item_id": menu_item["id"], "quantity": 1,
            "modifier_ids": [], "line_total_cents": line_total,
            "line_calories": line_cal, "effective_allergen_tags": tags,
        })
        db.order_lines[line["id"]] = line

        slot["reserved_count"] += 1
        db.touch(slot)

    recompute_queue_status(store)
    return success(serialize("pickup_slot", slot), 201)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_roles(role, {"PlatformAdmin"})
    data = body()
    require_fields(data, ["to_iso8601"])
    require_str(data, "to_iso8601")
    # validate parseable
    try:
        parse_iso(data["to_iso8601"])
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid timestamp.")
    db.clock_now_iso = data["to_iso8601"]
    # moving the clock changes the active-slot set -> recompute queue posture
    for store in db.stores.values():
        recompute_queue_status(store)
    return success({}, 200)
