"""Order lifecycle: create/read/list, lines, pay, place, cancel, and store-side
queue ops (start-prep, ready, complete, refund). Plus refunds list/get.

Validation ordering follows PRD §3.11.
"""
from datetime import datetime, timedelta

from flask import Blueprint, request

import errors
import helpers
from db import db, new_id, iso_now
from clock import clock
from middleware import authenticate, require_roles, require_owner
from response import success_object, success_array
from services import serializers
from services import projections
from services.mutations import touch, append_wallet_txn, append_star_ledger
from services import calculations

bp = Blueprint("orders", __name__)

RESERVED_STATES = ("PLACED", "IN_PREP", "READY")


def _expiry_after_now(reward):
    """expires_at strictly after current time."""
    exp = helpers.parse_iso8601(reward["expires_at"])
    return exp is not None and exp > clock.now()


# ===================== Order create / read / list =====================
@bp.route("/members/<member_id>/orders", methods=["POST"])
def create_order(member_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    require_owner(principal, member_id)

    body = helpers.get_json_body()
    helpers.require_fields(body, ["store_id", "pickup_slot_id"])
    store_id = body["store_id"]
    pickup_slot_id = body["pickup_slot_id"]
    applied_reward_id = body.get("applied_reward_id")

    # FK existence (ERR_REFERENCE_NOT_FOUND)
    store = db.stores.get(store_id)
    if store is None:
        raise errors.reference_not_found("store_id does not exist")
    slot = db.pickup_slots.get(pickup_slot_id)
    if slot is None:
        raise errors.reference_not_found("pickup_slot_id does not exist")
    if applied_reward_id is not None:
        if db.rewards.get(applied_reward_id) is None:
            raise errors.reference_not_found("applied_reward_id does not exist")

    # Slot suitability: slot belongs to the order's store, not in the past, and
    # window_start - now >= prep_minutes (ERR_SLOT_UNAVAILABLE).
    _check_slot_available(store, slot)

    now = iso_now()
    oid = new_id()
    order = {
        "id": oid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "member_id": member_id,
        "store_id": store_id,
        "pickup_slot_id": pickup_slot_id,
        "applied_reward_id": applied_reward_id,
        "subtotal_cents": 0,
        "reward_discount_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "stars_earned": 0,
        "fulfillment_status": "CART",
        "payment_status": "UNPAID",
        "pay_method": None,
    }
    db.orders[oid] = order
    return success_object(serializers.order_out(order), 201)


def _check_slot_available(store, slot):
    if slot["store_id"] != store["id"]:
        raise errors.slot_unavailable("Slot does not belong to the order's store")
    ws = helpers.parse_iso8601(slot["window_start"])
    now = clock.now()
    if ws is None:
        raise errors.slot_unavailable("Slot window invalid")
    # not in the past
    if ws < now:
        raise errors.slot_unavailable("Slot window is in the past")
    # lead time: window_start - now >= prep_minutes
    if ws - now < timedelta(minutes=store["prep_minutes"]):
        raise errors.slot_unavailable("Slot violates store lead time")


@bp.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    order = db.orders.get(order_id)
    if order is None:
        raise errors.not_found()
    require_owner(principal, order["member_id"])
    return success_object(serializers.order_out(order), 200)


@bp.route("/members/<member_id>/orders/<order_id>", methods=["GET"])
def get_order_scoped(member_id, order_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["member_id"] != member_id:
        raise errors.not_found()
    require_owner(principal, order["member_id"])
    return success_object(serializers.order_out(order), 200)


@bp.route("/orders", methods=["GET"])
def list_orders():
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    limit, offset = helpers.parse_pagination()
    items = list(db.orders.values())
    for key in ("member_id", "store_id", "pickup_slot_id", "applied_reward_id",
                "fulfillment_status"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    total = len(items)
    page = helpers.paginate(items, limit, offset)
    return success_array([serializers.order_out(o) for o in page], limit, offset, total, 200)


# ===================== Order lines =====================
@bp.route("/members/<member_id>/orders/<order_id>/lines", methods=["POST"])
def add_line(member_id, order_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["member_id"] != member_id:
        raise errors.not_found()
    require_owner(principal, order["member_id"])

    body = helpers.get_json_body()
    helpers.require_fields(body, ["menu_item_id", "quantity"])
    menu_item_id = body["menu_item_id"]
    # FK existence (ERR_REFERENCE_NOT_FOUND)
    menu_item = db.menu_items.get(menu_item_id)
    if menu_item is None:
        raise errors.reference_not_found("menu_item_id does not exist")

    modifiers_in = body.get("modifiers")
    if modifiers_in is None:
        modifiers_in = []
    if not isinstance(modifiers_in, list):
        raise errors.invalid_request("modifiers must be an array")

    # Validate modifier selections: well-formed + each option exists + belongs to item.
    normalized = []
    options_by_id = {}
    for sel in modifiers_in:
        if not isinstance(sel, dict):
            raise errors.invalid_request("each modifier must be an object")
        if "modifier_option_id" not in sel or "count" not in sel:
            raise errors.invalid_request("modifier requires modifier_option_id and count")
        opt_id = sel["modifier_option_id"]
        count = sel["count"]
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise errors.invalid_request("modifier count must be a positive integer")
        opt = db.modifier_options.get(opt_id)
        if opt is None:
            raise errors.reference_not_found("modifier_option_id does not exist")
        if opt["menu_item_id"] != menu_item_id:
            # option belongs to a different item -> malformed (ERR_INVALID_REQUEST)
            raise errors.invalid_request("modifier option does not belong to the line's menu item")
        if count > opt["max_quantity"]:
            raise errors.invalid_request("modifier count exceeds max_quantity")
        options_by_id[opt_id] = opt
        normalized.append({"modifier_option_id": opt_id, "count": count})

    # quantity well-formed
    quantity = helpers.require_int(body["quantity"], "quantity")
    if quantity < 1:
        raise errors.invalid_request("quantity must be at least 1")

    # State: order must be in CART
    if order["fulfillment_status"] != "CART":
        raise errors.invalid_state("Order is not in CART")
    # menu item must be available
    if not menu_item["available"]:
        raise errors.invalid_request("Menu item is not available")

    unit_price, line_total = calculations.compute_line_pricing(
        menu_item, normalized, quantity, options_by_id)

    now = iso_now()
    lid = new_id()
    line = {
        "id": lid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "order_id": order_id,
        "menu_item_id": menu_item_id,
        "quantity": quantity,
        "modifiers": normalized,
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "is_reward_redeemed": False,
    }
    db.order_lines[lid] = line
    return success_object(serializers.order_line_out(line), 201)


@bp.route("/order-lines", methods=["GET"])
def list_order_lines():
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    limit, offset = helpers.parse_pagination()
    items = list(db.order_lines.values())
    order_id = request.args.get("order_id")
    menu_item_id = request.args.get("menu_item_id")
    if order_id is not None:
        items = [l for l in items if l["order_id"] == order_id]
    if menu_item_id is not None:
        items = [l for l in items if l["menu_item_id"] == menu_item_id]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    total = len(items)
    page = helpers.paginate(items, limit, offset)
    return success_array([serializers.order_line_out(l) for l in page], limit, offset, total, 200)


@bp.route("/order-lines/<order_line_id>", methods=["GET"])
def get_order_line(order_line_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    line = db.order_lines.get(order_line_id)
    if line is None:
        raise errors.not_found()
    return success_object(serializers.order_line_out(line), 200)


# ===================== Pay =====================
@bp.route("/members/<member_id>/orders/<order_id>/pay", methods=["POST"])
def pay_order(member_id, order_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["member_id"] != member_id:
        raise errors.not_found()
    require_owner(principal, order["member_id"])

    body = helpers.get_json_body()
    helpers.require_fields(body, ["pay_method"])
    pay_method = helpers.require_enum(body["pay_method"], "pay_method",
                                      {"STORED_VALUE", "EXTERNAL_CARD"})

    # State preconditions: payment UNPAID and fulfillment CART, >=1 line
    if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "CART":
        raise errors.invalid_state("Order not in a payable state")
    lines = calculations.lines_for_order(order_id)
    if len(lines) < 1:
        raise errors.invalid_state("Order has no lines")

    # Resolve applied reward (lazy expiry handled below).
    reward = None
    if order["applied_reward_id"] is not None:
        reward = db.rewards.get(order["applied_reward_id"])
        # reward existence already validated at order create; re-check defensively
        if reward is None:
            raise errors.reference_not_found("applied_reward_id does not exist")

    # Reward applicability (ERR_REWARD_NOT_APPLICABLE), priority 9.
    if reward is not None:
        # lazy expiry: ISSUED & expired -> EXPIRED
        if reward["status"] == "ISSUED" and not _expiry_after_now(reward):
            reward["status"] = "EXPIRED"
            touch(reward)
        if reward["member_id"] != member_id:
            raise errors.reward_not_applicable("Reward not owned by member")
        if reward["status"] != "ISSUED":
            raise errors.reward_not_applicable("Reward is not ISSUED")
        if not _expiry_after_now(reward):
            raise errors.reward_not_applicable("Reward is expired")
        eligible = [l for l in lines if db.menu_items[l["menu_item_id"]]["reward_eligible"]]
        if len(eligible) < 1:
            raise errors.reward_not_applicable("No reward-eligible line")

    # Finalize totals (calc order_total).
    totals = calculations.compute_order_total(order, reward)

    card = projections.card_for_member(member_id)

    if pay_method == "STORED_VALUE":
        # OCC: expected_card_version must match the card's current version, priority 13.
        # ERR_INSUFFICIENT_BALANCE (priority 12) is checked before OCC per §3.11 ordering.
        expected = body.get("expected_card_version")
        balance = projections.card_balance_cents(card["id"])

        # auto-reload: enabled, balance <= threshold, AND balance < total
        auto_reload_will_fire = (
            card["auto_reload_enabled"]
            and balance <= card["auto_reload_threshold_cents"]
            and balance < totals["total_cents"]
        )
        projected_balance = balance + (card["auto_reload_amount_cents"] if auto_reload_will_fire else 0)

        # Insufficient balance after any auto-reload (ERR_INSUFFICIENT_BALANCE, 402)
        if projected_balance < totals["total_cents"]:
            raise errors.insufficient_balance()

        # OCC check (ERR_STALE_VERSION, 412)
        if expected is not None:
            if not isinstance(expected, int) or isinstance(expected, bool):
                raise errors.invalid_request("expected_card_version must be an integer")
            if expected != card["version"]:
                raise errors.stale_version("expected_card_version is stale")

        # Commit: auto-reload first (if firing), then ORDER_SPEND.
        if auto_reload_will_fire:
            append_wallet_txn(card["id"], "AUTO_RELOAD", card["auto_reload_amount_cents"],
                              order_id=order["id"])
            touch(card)  # balance recomputed + version increments by one
        append_wallet_txn(card["id"], "ORDER_SPEND", -totals["total_cents"], order_id=order["id"])
        touch(card)

    # Apply totals to the order.
    order["subtotal_cents"] = totals["subtotal_cents"]
    order["reward_discount_cents"] = totals["reward_discount_cents"]
    order["tax_cents"] = totals["tax_cents"]
    order["total_cents"] = totals["total_cents"]

    # Mark the redeemed line.
    if totals["redeemed_line_id"] is not None:
        redeemed_line = db.order_lines.get(totals["redeemed_line_id"])
        if redeemed_line is not None:
            redeemed_line["is_reward_redeemed"] = True
            touch(redeemed_line)

    # Stars earned at the member's CURRENT tier at pay time.
    current_lifetime = projections.lifetime_stars(member_id)
    current_tier = projections.tier_for(current_lifetime)
    stars = calculations.compute_stars_earned(
        current_tier, pay_method, order["total_cents"], order["tax_cents"])
    order["stars_earned"] = stars

    order["pay_method"] = pay_method
    order["payment_status"] = "PAID"

    # Append EARN ledger entry; member star figures/tier re-derived (touch member).
    append_star_ledger(member_id, "EARN", stars, order_id=order["id"])
    touch(member)

    # Reserve reward (ISSUED -> RESERVED).
    if reward is not None:
        reward["status"] = "RESERVED"
        reward["reserved_by_order_id"] = order["id"]
        touch(reward)

    touch(order)
    return success_object(serializers.order_out(order), 200)


# ===================== Place =====================
@bp.route("/members/<member_id>/orders/<order_id>/place", methods=["POST"])
def place_order(member_id, order_id):
    principal = authenticate()
    require_roles(principal, ["Member"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["member_id"] != member_id:
        raise errors.not_found()
    require_owner(principal, order["member_id"])

    body = helpers.get_json_body()
    # expected_slot_version is required for the OCC check (§2.8 / §3.6).
    helpers.require_fields(body, ["expected_slot_version"])
    expected = body["expected_slot_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise errors.invalid_request("expected_slot_version must be an integer")

    # State: fulfillment CART and payment PAID, >=1 line
    if order["fulfillment_status"] != "CART" or order["payment_status"] != "PAID":
        raise errors.invalid_state("Order not in a placeable state")
    lines = calculations.lines_for_order(order_id)
    if len(lines) < 1:
        raise errors.invalid_state("Order has no lines")

    store = db.stores.get(order["store_id"])
    slot = db.pickup_slots.get(order["pickup_slot_id"])

    # Store open (ERR_STORE_PAUSED, priority 7)
    if store["status"] != "OPEN":
        raise errors.store_paused()

    # Slot suitability re-check at place (ERR_SLOT_UNAVAILABLE, priority 8)
    _check_slot_available(store, slot)

    # Remaining capacity (ERR_SLOT_FULL, priority 11): reserved_count < slot_capacity
    reserved = projections.slot_reserved_count(slot["id"])
    if reserved >= store["slot_capacity"]:
        raise errors.slot_full()

    # OCC (ERR_STALE_VERSION, priority 13)
    if expected != slot["version"]:
        raise errors.stale_version("expected_slot_version is stale")

    # Commit: CART -> PLACED
    order["fulfillment_status"] = "PLACED"
    touch(order)
    # slot reserved_count recomputed (derived) + version increments by one
    touch(slot)

    # Consume reward: RESERVED -> REDEEMED
    if order["applied_reward_id"] is not None:
        reward = db.rewards.get(order["applied_reward_id"])
        if reward is not None and reward["status"] == "RESERVED":
            reward["status"] = "REDEEMED"
            touch(reward)

    return success_object(serializers.order_out(order), 200)


# ===================== Cancel =====================
@bp.route("/members/<member_id>/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(member_id, order_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator"])
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["member_id"] != member_id:
        raise errors.not_found()
    require_owner(principal, order["member_id"])

    # State: cancel only while PLACED (ERR_INVALID_STATE)
    if order["fulfillment_status"] != "PLACED":
        raise errors.invalid_state("Order is not PLACED")
    # Refund eligibility: PAID and not PICKED_UP (ERR_REFUND_NOT_ALLOWED)
    if order["payment_status"] != "PAID" or order["fulfillment_status"] == "PICKED_UP":
        raise errors.refund_not_allowed()

    # fulfillment PLACED -> CANCELLED, then compensating refund cascade to STORED_VALUE.
    order["fulfillment_status"] = "CANCELLED"
    _perform_refund_cascade(order, member, destination="STORED_VALUE")
    touch(order)
    return success_object(serializers.order_out(order), 200)


# ===================== Store-side queue ops =====================
@bp.route("/stores/<store_id>/orders/<order_id>/start-prep", methods=["POST"])
def start_prep(store_id, order_id):
    principal = authenticate()
    require_roles(principal, ["StoreOperator"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["store_id"] != store_id:
        raise errors.not_found()
    if order["fulfillment_status"] != "PLACED":
        raise errors.invalid_state("Order is not PLACED")
    if store["status"] != "OPEN":
        raise errors.store_paused()
    order["fulfillment_status"] = "IN_PREP"
    touch(order)
    return success_object(serializers.order_out(order), 200)


@bp.route("/stores/<store_id>/orders/<order_id>/ready", methods=["POST"])
def mark_ready(store_id, order_id):
    principal = authenticate()
    require_roles(principal, ["StoreOperator"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["store_id"] != store_id:
        raise errors.not_found()
    if order["fulfillment_status"] != "IN_PREP":
        raise errors.invalid_state("Order is not IN_PREP")
    order["fulfillment_status"] = "READY"
    touch(order)
    return success_object(serializers.order_out(order), 200)


@bp.route("/stores/<store_id>/orders/<order_id>/complete", methods=["POST"])
def complete_order(store_id, order_id):
    principal = authenticate()
    require_roles(principal, ["StoreOperator"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["store_id"] != store_id:
        raise errors.not_found()
    if order["fulfillment_status"] != "READY":
        raise errors.invalid_state("Order is not READY")
    order["fulfillment_status"] = "PICKED_UP"
    touch(order)
    # slot reserved_count recomputed (order leaves the reserved set) + version bump
    slot = db.pickup_slots.get(order["pickup_slot_id"])
    if slot is not None:
        touch(slot)
    return success_object(serializers.order_out(order), 200)


# ===================== Refund (operator) =====================
@bp.route("/stores/<store_id>/orders/<order_id>/refund", methods=["POST"])
def refund_order(store_id, order_id):
    principal = authenticate()
    require_roles(principal, ["StoreOperator", "PlatformAdmin"])
    store = db.stores.get(store_id)
    if store is None:
        raise errors.not_found()
    order = db.orders.get(order_id)
    if order is None or order["store_id"] != store_id:
        raise errors.not_found()

    body = helpers.get_json_body()
    helpers.require_fields(body, ["destination"])
    destination = helpers.require_enum(body["destination"], "destination",
                                       {"STORED_VALUE", "ORIGINAL_METHOD"})

    # Refund eligibility: PAID and not PICKED_UP (ERR_REFUND_NOT_ALLOWED)
    if order["payment_status"] != "PAID" or order["fulfillment_status"] == "PICKED_UP":
        raise errors.refund_not_allowed()

    member = db.members.get(order["member_id"])
    refund = _perform_refund_cascade(order, member, destination=destination)
    # fulfillment -> CANCELLED if non-terminal
    if order["fulfillment_status"] not in ("PICKED_UP", "CANCELLED"):
        order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success_object(serializers.refund_out(refund), 201)


def _perform_refund_cascade(order, member, destination):
    """Shared compensating cascade for cancel and operator refund (PRD §3.8).

    Creates a Refund(SETTLED), flips payment_status PAID -> REFUNDED, returns money
    to the wallet when destination==STORED_VALUE or original pay was STORED_VALUE,
    reverses stars, restores a redeemed reward, and recomputes the slot.
    Returns the Refund dict.
    """
    total = order["total_cents"]
    stars = order["stars_earned"]

    # payment PAID -> REFUNDED
    order["payment_status"] = "REFUNDED"

    # Wallet refund when destination STORED_VALUE or original pay was STORED_VALUE.
    if destination == "STORED_VALUE" or order["pay_method"] == "STORED_VALUE":
        card = projections.card_for_member(order["member_id"])
        if card is not None:
            append_wallet_txn(card["id"], "REFUND", total, order_id=order["id"])
            touch(card)

    # Star reversal: REVERSAL, -stars_earned.
    append_star_ledger(order["member_id"], "REVERSAL", -stars, order_id=order["id"])
    if member is not None:
        touch(member)

    # Restore a redeemed/reserved reward: -> ISSUED (or EXPIRED if past expiry).
    if order["applied_reward_id"] is not None:
        reward = db.rewards.get(order["applied_reward_id"])
        if reward is not None and reward["status"] in ("REDEEMED", "RESERVED"):
            if _expiry_after_now(reward):
                reward["status"] = "ISSUED"
            else:
                reward["status"] = "EXPIRED"
            reward["reserved_by_order_id"] = None
            touch(reward)

    # Slot reserved_count recomputed + version bump.
    slot = db.pickup_slots.get(order["pickup_slot_id"])
    if slot is not None:
        touch(slot)

    # Create the Refund record in terminal SETTLED state.
    now = iso_now()
    rid = new_id()
    refund = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "order_id": order["id"],
        "amount_cents": total,
        "destination": destination,
        "stars_reversed": stars,
    }
    db.refunds[rid] = refund
    return refund


# ===================== Refund reads =====================
@bp.route("/refunds", methods=["GET"])
def list_refunds():
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    limit, offset = helpers.parse_pagination()
    items = list(db.refunds.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = helpers.paginate(items, limit, offset)
    return success_array([serializers.refund_out(r) for r in page], limit, offset, total, 200)


@bp.route("/refunds/<refund_id>", methods=["GET"])
def get_refund(refund_id):
    principal = authenticate()
    require_roles(principal, ["Member", "StoreOperator", "PlatformAdmin"])
    r = db.refunds.get(refund_id)
    if r is None:
        raise errors.not_found()
    return success_object(serializers.refund_out(r), 200)
