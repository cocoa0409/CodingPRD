"""Orders, order lines, and the order lifecycle (place/advance/complete/cancel/make-it-right)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import err
from helpers import (body, require_fields, require_str, require_int,
                     get_or_404, fk_or_404, paginate, filter_by)
from middleware import get_auth, require_roles, require_owner
from response import success
from serializers import serialize
from services import pricing
from services.loyalty import append_ledger_entry, account_for_customer
from services.queue import recompute_queue_status

bp = Blueprint("orders", __name__)

NON_TERMINAL_ORDER = {"CART", "PLACED", "PREPARING", "READY"}


# ---------------- helpers ----------------
def _lines_of(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


def _applied_subscription(order):
    if not order.get("subscription_id"):
        return None
    return db.subscriptions.get(order["subscription_id"])


# ---------------- Orders CRUD ----------------
@bp.post("/orders")
def create_order():
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    data = body()
    require_fields(data, ["customer_id", "store_id", "pickup_slot_id"])
    require_str(data, "customer_id")
    require_str(data, "store_id")
    require_str(data, "pickup_slot_id")
    require_owner(role, user_id, data["customer_id"])
    fk_or_404("customer", data["customer_id"])
    fk_or_404("store", data["store_id"])
    slot = fk_or_404("pickup_slot", data["pickup_slot_id"])
    sub_id = data.get("subscription_id")
    fk_or_404("subscription", sub_id)

    order = db.common_fields()
    order.update({
        "customer_id": data["customer_id"],
        "store_id": data["store_id"],
        "pickup_slot_id": data["pickup_slot_id"],
        "subscription_id": sub_id,
        "channel": slot["channel"],  # copied from slot
        "order_status": "CART",
        "settlement_status": "UNSETTLED",
        "subtotal_cents": 0,
        "delivery_fee_cents": 0,
        "points_redeemed": 0,
        "discount_cents": 0,
        "wallet_applied_cents": 0,
        "total_cents": 0,
        "total_calories": 0,
        "points_earned": 0,
        "refunded_cents": 0,
    })
    db.orders[order["id"]] = order
    return success(serialize("order", order), 201)


@bp.get("/orders/<oid>")
def get_order(oid):
    get_auth()
    order = get_or_404("order", oid)
    return success(serialize("order", order), 200)


@bp.get("/orders")
def list_orders():
    get_auth()
    items = filter_by(
        db.orders,
        customer_id=request.args.get("customer_id"),
        store_id=request.args.get("store_id"),
        pickup_slot_id=request.args.get("pickup_slot_id"),
        subscription_id=request.args.get("subscription_id"),
    )
    page, meta = paginate(items)
    return success([serialize("order", o) for o in page], 200, meta)


# ---------------- Order lines ----------------
def _resolve_modifiers(menu_item, modifier_ids):
    """Validate FK existence then modifier-belongs-to-item (ERR_MODIFIER_MISMATCH)."""
    mods = []
    for mid in modifier_ids:
        mod = fk_or_404("modifier", mid)  # existence first (priority 3)
        mods.append(mod)
    # referential business rule (priority 5)
    for mod in mods:
        if mod["menu_item_id"] != menu_item["id"]:
            raise err("ERR_MODIFIER_MISMATCH", "Modifier does not belong to the menu item.")
    return mods


@bp.post("/orders/<oid>/lines")
def add_line(oid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    order = get_or_404("order", oid)
    require_owner(role, user_id, order["customer_id"])
    data = body()
    require_fields(data, ["menu_item_id", "quantity"])
    require_str(data, "menu_item_id")
    require_int(data, "quantity")
    if "modifier_ids" in data and data["modifier_ids"] is not None:
        if not isinstance(data["modifier_ids"], list):
            raise err("ERR_INVALID_REQUEST", "modifier_ids must be an array.")
    # state: only a CART order accepts new lines
    if order["order_status"] != "CART":
        raise err("ERR_INVALID_STATE", "Lines can only be added to a CART order.")
    menu_item = fk_or_404("menu_item", data["menu_item_id"])
    # item must belong to the order's store (ERR_MODIFIER_MISMATCH per §3.11)
    if menu_item["store_id"] != order["store_id"]:
        raise err("ERR_MODIFIER_MISMATCH", "Menu item does not belong to the order's store.")
    if data["quantity"] < 1:
        raise err("ERR_INVALID_QUANTITY", "quantity must be >= 1.")
    # item availability / store active
    store = db.stores.get(order["store_id"])
    if not menu_item["is_available"] or (store and not store["is_active"]):
        raise err("ERR_ITEM_UNAVAILABLE", "Menu item or store unavailable.")

    modifier_ids = data.get("modifier_ids") or []
    mods = _resolve_modifiers(menu_item, modifier_ids)
    line_total, line_cal, tags = pricing.compute_line(menu_item, mods, data["quantity"])

    line = db.common_fields()
    line.update({
        "order_id": oid,
        "menu_item_id": data["menu_item_id"],
        "quantity": data["quantity"],
        "modifier_ids": modifier_ids,
        "line_total_cents": line_total,
        "line_calories": line_cal,
        "effective_allergen_tags": tags,
    })
    db.order_lines[line["id"]] = line
    pricing.recompute_order_lines_totals(order)
    db.touch(order)
    return success(serialize("order_line", line), 201)


@bp.get("/order-lines/<lid>")
def get_line(lid):
    get_auth()
    line = get_or_404("order_line", lid)
    return success(serialize("order_line", line), 200)


@bp.get("/order-lines")
def list_lines():
    get_auth()
    items = filter_by(
        db.order_lines,
        order_id=request.args.get("order_id"),
        menu_item_id=request.args.get("menu_item_id"),
    )
    page, meta = paginate(items)
    return success([serialize("order_line", l) for l in page], 200, meta)


@bp.patch("/order-lines/<lid>")
def update_line(lid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    line = get_or_404("order_line", lid)
    order = db.orders[line["order_id"]]
    require_owner(role, user_id, order["customer_id"])
    data = body()
    if "quantity" in data and data["quantity"] is not None:
        require_int(data, "quantity")
    if "modifier_ids" in data and data["modifier_ids"] is not None:
        if not isinstance(data["modifier_ids"], list):
            raise err("ERR_INVALID_REQUEST", "modifier_ids must be an array.")
    # state: only CART order lines may be updated
    if order["order_status"] != "CART":
        raise err("ERR_INVALID_STATE", "Lines can only be updated on a CART order.")

    menu_item = db.menu_items[line["menu_item_id"]]
    new_qty = data.get("quantity", line["quantity"])
    if new_qty is None:
        new_qty = line["quantity"]
    if new_qty < 1:
        raise err("ERR_INVALID_QUANTITY", "quantity must be >= 1.")
    if "modifier_ids" in data and data["modifier_ids"] is not None:
        new_modifier_ids = data["modifier_ids"]
    else:
        new_modifier_ids = line["modifier_ids"]
    mods = _resolve_modifiers(menu_item, new_modifier_ids)
    line_total, line_cal, tags = pricing.compute_line(menu_item, mods, new_qty)

    line["quantity"] = new_qty
    line["modifier_ids"] = new_modifier_ids
    line["line_total_cents"] = line_total
    line["line_calories"] = line_cal
    line["effective_allergen_tags"] = tags
    db.touch(line)
    pricing.recompute_order_lines_totals(order)
    db.touch(order)
    return success(serialize("order_line", line), 200)


# ---------------- Place ----------------
@bp.post("/orders/<oid>/place")
def place_order(oid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    order = get_or_404("order", oid)
    require_owner(role, user_id, order["customer_id"])
    data = body()
    # expected_pickup_slot_version is mandatory
    require_fields(data, ["expected_pickup_slot_version"])
    require_int(data, "expected_pickup_slot_version")
    if "points_redeemed" in data and data["points_redeemed"] is not None:
        require_int(data, "points_redeemed")
    points_redeemed = data.get("points_redeemed", 0) or 0

    # state (priority 6): only CART -> PLACED
    if order["order_status"] != "CART":
        raise err("ERR_INVALID_STATE", "Only a CART order may be placed.")

    store = db.stores[order["store_id"]]
    slot = db.pickup_slots[order["pickup_slot_id"]]
    customer = db.customers[order["customer_id"]]
    lines = _lines_of(oid)

    # empty order gate (ERR_EMPTY_ORDER)
    if len(lines) == 0:
        raise err("ERR_EMPTY_ORDER", "Order has no lines.")

    # allergen safety gate (priority 7)
    blocklist = set(customer.get("allergen_blocklist") or [])
    for line in lines:
        if blocklist.intersection(set(line["effective_allergen_tags"])):
            raise err("ERR_ALLERGEN_BLOCKED", "Order contains a blocked allergen.")

    # slot availability gate (priority 8): clock < window_end AND not closed AND channel matches
    clock = db.clock_dt()
    window_end = parse_iso(slot["window_end_utc"])
    if slot["is_closed"] or clock >= window_end or order["channel"] != slot["channel"]:
        raise err("ERR_SLOT_UNAVAILABLE", "Pickup slot unavailable.")

    # slot capacity gate (priority 9): strict <
    if slot["reserved_count"] >= store["throughput_capacity_per_slot"]:
        raise err("ERR_SLOT_CAPACITY_EXCEEDED", "Slot at capacity.")

    # locker availability gate (priority 10)
    if order["channel"] == "LOCKER":
        non_terminal_locker = 0
        for o in db.orders.values():
            if (o["store_id"] == store["id"] and o["channel"] == "LOCKER"
                    and o["order_status"] in NON_TERMINAL_ORDER and o["id"] != oid):
                non_terminal_locker += 1
        if non_terminal_locker >= store["locker_count"]:
            raise err("ERR_NO_LOCKER_AVAILABLE", "No locker available.")

    # sufficient points gate (priority 11)
    acct = account_for_customer(order["customer_id"])
    if points_redeemed > acct["points_balance"]:
        raise err("ERR_INSUFFICIENT_POINTS", "points_redeemed exceeds balance.")

    # OCC gate (priority 13)
    if data["expected_pickup_slot_version"] != slot["version"]:
        raise err("ERR_STALE_SLOT_VERSION", "Slot version is stale.")

    # ---- pricing waterfall (pinned order) ----
    pricing.recompute_order_lines_totals(order)
    subtotal = order["subtotal_cents"]
    sub = _applied_subscription(order)
    sub_active_free_delivery = False
    if sub and sub["status"] == "ACTIVE":
        plan = db.subscription_plans.get(sub["plan_id"])
        if plan and plan["free_delivery"]:
            sub_active_free_delivery = True
    fee = pricing.delivery_fee(order["channel"], store["state_code"], subtotal,
                              sub_active_free_delivery)
    discount = pricing.redemption_value(points_redeemed, subtotal)
    wallet_applied, total = pricing.order_total(
        subtotal, discount, fee, customer["wallet_credit_cents"])

    order["points_redeemed"] = points_redeemed
    order["delivery_fee_cents"] = fee
    order["discount_cents"] = discount
    order["wallet_applied_cents"] = wallet_applied
    order["total_cents"] = total
    order["order_status"] = "PLACED"
    order["settlement_status"] = "CAPTURED"

    # commit reservation & money movement
    slot["reserved_count"] += 1
    db.touch(slot)  # version bump
    if points_redeemed > 0:
        append_ledger_entry(acct["id"], -points_redeemed, "REDEEM", order_id=oid)
    customer["wallet_credit_cents"] -= wallet_applied
    db.touch(customer)
    db.touch(order)
    recompute_queue_status(store)
    return success(serialize("order", order), 200)


# ---------------- Advance ----------------
@bp.post("/orders/<oid>/advance")
def advance_order(oid):
    _, role = get_auth()
    require_roles(role, {"StoreManager"})
    order = get_or_404("order", oid)
    store = db.stores[order["store_id"]]
    status = order["order_status"]
    if status == "PLACED":
        if not store["is_active"]:
            raise err("ERR_INVALID_STATE", "Store is not active.")
        order["order_status"] = "PREPARING"
    elif status == "PREPARING":
        order["order_status"] = "READY"
    else:
        raise err("ERR_INVALID_STATE", "Order cannot be advanced from current state.")
    db.touch(order)
    return success(serialize("order", order), 200)


# ---------------- Complete ----------------
@bp.post("/orders/<oid>/complete")
def complete_order(oid):
    _, role = get_auth()
    require_roles(role, {"StoreManager"})
    order = get_or_404("order", oid)
    if order["order_status"] != "READY":
        raise err("ERR_INVALID_STATE", "Only a READY order may be completed.")

    store = db.stores[order["store_id"]]
    slot = db.pickup_slots[order["pickup_slot_id"]]
    acct = account_for_customer(order["customer_id"])

    # points earned (dual-variant)
    sub = _applied_subscription(order)
    sub_active = bool(sub and sub["status"] == "ACTIVE")
    multiplier = 10000
    if sub_active:
        plan = db.subscription_plans.get(sub["plan_id"])
        if plan:
            multiplier = plan["points_multiplier_bps"]
    earned = pricing.points_earned(order["subtotal_cents"], order["discount_cents"],
                                   sub_active, multiplier)
    order["order_status"] = "COMPLETED"
    order["points_earned"] = earned
    db.touch(order)
    append_ledger_entry(acct["id"], earned, "EARN", order_id=oid)

    # release slot
    slot["reserved_count"] -= 1
    db.touch(slot)
    recompute_queue_status(store)

    # challenge cascade (depth-3)
    for ch in db.loyalty_challenges.values():
        if ch["customer_id"] == order["customer_id"] and ch["status"] == "IN_PROGRESS":
            ch["progress_count"] += 1
            if ch["progress_count"] >= ch["target_order_count"]:
                ch["status"] = "ROUND_COMPLETE"
                ch["rounds_completed"] += 1
                append_ledger_entry(acct["id"], ch["bonus_points"],
                                    "CHALLENGE_BONUS", order_id=oid)
            db.touch(ch)

    return success(serialize("order", order), 200)


# ---------------- Cancel ----------------
@bp.post("/orders/<oid>/cancel")
def cancel_order(oid):
    user_id, role = get_auth()
    require_roles(role, {"Customer"})
    order = get_or_404("order", oid)
    require_owner(role, user_id, order["customer_id"])
    data = body()
    status = order["order_status"]

    if status == "CART":
        order["order_status"] = "CANCELLED"
        db.touch(order)
        return success(serialize("order", order), 200)

    if status in {"PLACED", "PREPARING"}:
        store = db.stores[order["store_id"]]
        slot = db.pickup_slots[order["pickup_slot_id"]]
        customer = db.customers[order["customer_id"]]
        acct = account_for_customer(order["customer_id"])

        order["settlement_status"] = "REFUNDED"
        # re-credit wallet applied; charged amount refunded per refund_destination
        # (ORIGINAL reverses off-ledger; WALLET destination unspecified for cancel,
        #  the wallet_applied re-credit is the in-system conserved movement)
        customer["wallet_credit_cents"] += order["wallet_applied_cents"]
        db.touch(customer)
        # restore redeemed points
        if order["points_redeemed"] > 0:
            append_ledger_entry(acct["id"], order["points_redeemed"],
                                "ADJUSTMENT", order_id=oid)
        # release slot, bump version
        slot["reserved_count"] -= 1
        db.touch(slot)
        order["refunded_cents"] += order["total_cents"]
        order["order_status"] = "CANCELLED"
        db.touch(order)
        recompute_queue_status(store)
        return success(serialize("order", order), 200)

    raise err("ERR_INVALID_STATE", "Order cannot be cancelled from current state.")


# ---------------- Make it right ----------------
@bp.post("/orders/<oid>/make-it-right")
def make_it_right(oid):
    _, role = get_auth()
    require_roles(role, {"StoreManager"})
    order = get_or_404("order", oid)
    data = body()
    require_fields(data, ["refund_amount_cents", "refund_destination"])
    require_int(data, "refund_amount_cents")
    require_str(data, "refund_destination")
    if data["refund_destination"] not in {"WALLET", "ORIGINAL"}:
        raise err("ERR_INVALID_REQUEST", "refund_destination must be WALLET or ORIGINAL.")

    # state (priority 6): order_status in {PREPARING, READY, COMPLETED}
    if order["order_status"] not in {"PREPARING", "READY", "COMPLETED"}:
        raise err("ERR_INVALID_STATE", "Order not in a refundable order_status.")
    if order["settlement_status"] not in {"CAPTURED", "PARTIALLY_REFUNDED"}:
        raise err("ERR_INVALID_STATE", "Order not in a refundable settlement state.")

    amount = data["refund_amount_cents"]
    remaining = order["total_cents"] - order["refunded_cents"]
    # fiscal gate (priority 12)
    if amount <= 0 or amount > remaining:
        raise err("ERR_REFUND_EXCEEDS_CHARGE", "Invalid refund amount.")

    customer = db.customers[order["customer_id"]]
    acct = account_for_customer(order["customer_id"])

    # points clawback BEFORE mutating refunded_cents/order_status
    prior_clawback = _prior_clawback(oid)
    clawback = pricing.points_clawback(order, amount, prior_clawback)

    order["refunded_cents"] += amount
    if order["refunded_cents"] == order["total_cents"]:
        order["settlement_status"] = "REFUNDED"
    else:
        order["settlement_status"] = "PARTIALLY_REFUNDED"

    if data["refund_destination"] == "WALLET":
        customer["wallet_credit_cents"] += amount
        db.touch(customer)

    db.touch(order)

    if clawback > 0:
        append_ledger_entry(acct["id"], -clawback, "CLAWBACK", order_id=oid)

    return success(serialize("order", order), 200)


def _prior_clawback(order_id):
    total = 0
    for e in db.points_ledger_entries.values():
        if e["order_id"] == order_id and e["reason"] == "CLAWBACK":
            total += -e["delta_points"]
    return total
