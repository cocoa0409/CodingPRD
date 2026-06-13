"""Order endpoints + fulfillment/payment state machines.

PRD §2.6, §2.8, §3.2, §3.5, §3.6, §3.7, §3.8.
"""
from flask import Blueprint, request

import db
import clock
import calculations as calc
import lookups
from errors import (
    err,
    ERR_ORDER_NOT_FOUND, ERR_CUSTOMER_NOT_FOUND, ERR_SLOT_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND, ERR_PICKER_NOT_FOUND,
    ERR_CROSS_STORE_REFERENCE, ERR_PRODUCT_DISCONTINUED,
    ERR_CUSTOMER_SUSPENDED, ERR_STORE_CLOSED, ERR_STORE_NOT_FOUND,
    ERR_FORBIDDEN_ROLE, ERR_VALIDATION,
    ERR_SLOT_VERSION_STALE, ERR_SLOT_FULL, ERR_SLOT_CLOSED,
    ERR_INVALID_ORDER_STATE, ERR_PICKER_WINDOW_CONFLICT,
    ERR_LINES_NOT_RESOLVED, ERR_NOTHING_TO_STAGE,
    ERR_ORDER_NOT_STAGED, ERR_PAYMENT_NOT_CAPTURED,
    ERR_EBT_NOT_ACCEPTED, ERR_ORDER_ALREADY_HANDED_OFF,
    ERR_AGE_VERIFICATION_REQUIRED, ERR_AGE_VERIFICATION_FAILED,
    ERR_COLD_CHAIN_EXPIRED,
)
from middleware import get_user_context, require_role
import validate as V
from timeutil import parse_iso, iso_now_ms
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate
from datetime import timedelta

bp = Blueprint("orders", __name__)

# fulfillment_status values that count toward a slot's booked_count (PRD §2.6).
BOOKED_STATES = ("PLACED", "PICKING", "STAGED", "HANDED_OFF")


def _serialize(order):
    return public(order)


def _customer_owns(role, user_id, order):
    # Entity-backed Customer ownership: customer_id must equal X-User-ID.
    return not (role == "Customer" and order["customer_id"] != user_id)


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------
@bp.route("/v1/orders", methods=["POST"])
def place_order():
    user_id, role = get_user_context()
    require_role(role, {"Customer", "StoreOps"})  # PRD §4
    body = V.get_body()
    store_id = V.require_str(body, "store_id")
    customer_id = V.require_str(body, "customer_id")
    slot_id = V.require_str(body, "slot_id")
    expected_slot_version = V.require_int(body, "expected_slot_version")  # §2.8 non-optional
    tip_cents = V.opt_int(body, "tip_cents", 0, minimum=0)  # default 0, >= 0
    lines_in = V.require(body, "lines")
    if not isinstance(lines_in, list) or len(lines_in) == 0:
        err(ERR_VALIDATION, "lines must be a non-empty array")

    # PRD §2.1: a Customer places only their own order (X-User-ID == customer_id).
    if role == "Customer" and user_id != customer_id:
        err(ERR_FORBIDDEN_ROLE, "Customer may only place their own orders")

    # Validate each line shape up-front (ERR_VALIDATION before referential).
    parsed_lines = []
    for entry in lines_in:
        if not isinstance(entry, dict):
            err(ERR_VALIDATION, "each line must be an object")
        pid = V.require_str(entry, "product_id")
        requested_qty = V.require_number(entry, "requested_qty", positive=True)
        est_weight = V.opt_number(entry, "estimated_weight_kg", None, positive=True)
        sub_policy = V.opt_enum(
            entry, "substitution_policy",
            {"NO_SUBSTITUTION", "SAME_PRICE_OR_LESS", "SHOPPER_CHOICE"},
            "NO_SUBSTITUTION",
        )
        parsed_lines.append({
            "product_id": pid,
            "requested_qty": requested_qty,
            "estimated_weight_kg": est_weight,
            "substitution_policy": sub_policy,
        })

    with db.lock:
        # --- priority 4: referential integrity (PRD §2.10 / §3.2) ---
        customer = db.customers.get(customer_id)
        if customer is None:
            err(ERR_CUSTOMER_NOT_FOUND, "Customer not found")
        slot = db.slots.get(slot_id)
        if slot is None:
            err(ERR_SLOT_NOT_FOUND, "Slot not found")
        store = db.stores.get(store_id)
        if store is None:
            err(ERR_STORE_NOT_FOUND, "Store not found")
        # Resolve every product first.
        products = []
        for pl in parsed_lines:
            prod = db.products.get(pl["product_id"])
            if prod is None:
                err(ERR_PRODUCT_NOT_FOUND, "Product not found")
            products.append(prod)
        # Cross-store: slot and products must belong to store_id.
        if slot["store_id"] != store_id:
            err(ERR_CROSS_STORE_REFERENCE, "Slot belongs to a different store")
        for prod in products:
            if prod["store_id"] != store_id:
                err(ERR_CROSS_STORE_REFERENCE, "Product belongs to a different store")
        # Store ACTIVE, customer ACTIVE, no product DISCONTINUED.
        if store["status"] != "ACTIVE":
            err(ERR_STORE_CLOSED, "Store is CLOSED")
        if customer["status"] != "ACTIVE":
            err(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED")
        for prod in products:
            if prod["status"] == "DISCONTINUED":
                err(ERR_PRODUCT_DISCONTINUED, "Product is DISCONTINUED")
        # For WEIGHT products, estimated_weight_kg is required (PRD §3.2).
        for pl, prod in zip(parsed_lines, products):
            if prod["pricing_mode"] == "WEIGHT" and pl["estimated_weight_kg"] is None:
                err(ERR_VALIDATION, "estimated_weight_kg required for WEIGHT product")

        # --- priority 5: slot state (CLOSED rejects placement) ---
        if slot["status"] == "CLOSED":
            err(ERR_SLOT_CLOSED, "Slot is CLOSED")

        # --- priority 6: OCC then capacity (PRD §2.8 then §2.6) ---
        if expected_slot_version != slot["version"]:
            err(ERR_SLOT_VERSION_STALE, "expected_slot_version does not match slot version")
        if not (slot["booked_count"] < slot["capacity"]):
            err(ERR_SLOT_FULL, "Slot is full")

        # --- commit ---
        order = {
            "store_id": store_id,
            "customer_id": customer_id,
            "slot_id": slot_id,
            "picker_id": None,
            "fulfillment_status": "PLACED",
            "payment_status": "AUTHORIZED",
            "tip_cents": tip_cents,
            "estimated_total_cents": 0,
            "estimated_ebt_eligible_cents": 0,
            "final_total_cents": 0,
            "final_ebt_eligible_cents": 0,
            "ebt_charged_cents": 0,
            "card_charged_cents": 0,
            "refunded_total_cents": 0,
            "net_captured_cents": 0,
            "staged_at": None,
            "requires_age_check": False,
        }
        db.stamp_create(order)
        db.orders[order["id"]] = order

        for pl, prod in zip(parsed_lines, products):
            if prod["pricing_mode"] == "UNIT":
                est = calc.line_charge(prod, qty=pl["requested_qty"])
            else:
                est = calc.line_charge(prod, weight_kg=pl["estimated_weight_kg"])
            line = {
                "order_id": order["id"],
                "product_id": pl["product_id"],
                "requested_qty": pl["requested_qty"],
                "estimated_weight_kg": pl["estimated_weight_kg"],
                "picked_qty": None,
                "actual_weight_kg": None,
                "substitution_policy": pl["substitution_policy"],
                "estimated_line_cents": est,
                "final_line_cents": 0,
                "status": "PENDING",
            }
            db.stamp_create(line)
            db.order_lines[line["id"]] = line

        lookups.recompute_estimated_totals(order)

        # Slot booking: booked_count += 1, version += 1, FULL if at capacity.
        slot["booked_count"] += 1
        if slot["booked_count"] == slot["capacity"]:
            slot["status"] = "FULL"
        db.touch(slot)

        db.touch(order)
        return object_response(_serialize(order), 201)


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------
@bp.route("/v1/orders", methods=["GET"])
def list_orders():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    limit, offset = get_pagination()
    store_id = request.args.get("store_id")
    customer_id = request.args.get("customer_id")
    slot_id = request.args.get("slot_id")
    picker_id = request.args.get("picker_id")
    with db.lock:
        records = list(db.orders.values())
        if store_id is not None:
            records = [o for o in records if o["store_id"] == store_id]
        if customer_id is not None:
            records = [o for o in records if o["customer_id"] == customer_id]
        if slot_id is not None:
            records = [o for o in records if o["slot_id"] == slot_id]
        if picker_id is not None:
            records = [o for o in records if o["picker_id"] == picker_id]
        # Entity-backed scoping: a Customer sees only their own orders.
        if role == "Customer":
            records = [o for o in records if o["customer_id"] == user_id]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        if not _customer_owns(role, user_id, order):
            err(ERR_FORBIDDEN_ROLE, "Customer may only access their own orders")
        return object_response(_serialize(order))


# ---------------------------------------------------------------------------
# Claim (PLACED -> PICKING)
# ---------------------------------------------------------------------------
@bp.route("/v1/orders/<order_id>/claim", methods=["POST"])
def claim_order(order_id):
    user_id, role = get_user_context()
    require_role(role, {"Picker"})  # PRD §4: Picker only
    body = V.get_body()
    ws_raw = V.require_str(body, "window_start")
    we_raw = V.require_str(body, "window_end")
    try:
        ws = parse_iso(ws_raw)
        we = parse_iso(we_raw)
    except ValueError:
        err(ERR_VALIDATION, "window_start/window_end must be ISO 8601 instants")
    if not (we > ws):
        err(ERR_VALIDATION, "window_end must be strictly after window_start")

    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        # Entity-backed: X-User-ID must be a Picker of the order's store (PRD §2.1).
        picker = db.pickers.get(user_id)
        if picker is None or picker["store_id"] != order["store_id"]:
            err(ERR_FORBIDDEN_ROLE, "Picker must belong to the order's store")
        # --- priority 5: state ---
        if order["fulfillment_status"] != "PLACED":
            err(ERR_INVALID_ORDER_STATE, "Order is not PLACED")
        # acting picker must be AVAILABLE
        if picker["status"] != "AVAILABLE":
            err(ERR_INVALID_ORDER_STATE, "Picker is not AVAILABLE")
        # --- priority 6: picker window conflict (PRD §3.2) ---
        cooldown = timedelta(minutes=picker["window_cooldown_minutes"])
        for other in db.orders.values():
            if other["id"] == order_id:
                continue
            if other["picker_id"] != picker["id"]:
                continue
            held = other.get("_pick_window")
            if not held:
                continue
            h_start = parse_iso(held["window_start"]) - cooldown
            h_end = parse_iso(held["window_end"]) + cooldown
            # Buffered held window is closed on both ends; new window is
            # [ws, we). Conflict iff ws <= h_end and h_start <= we.
            if ws <= h_end and h_start <= we:
                err(ERR_PICKER_WINDOW_CONFLICT, "Pick window conflicts within cooldown buffer")
        # --- commit ---
        order["picker_id"] = picker["id"]
        order["fulfillment_status"] = "PICKING"
        order["_pick_window"] = {"window_start": ws_raw, "window_end": we_raw}
        db.touch(order)
        return object_response(_serialize(order))


# ---------------------------------------------------------------------------
# Stage (PICKING -> STAGED)
# ---------------------------------------------------------------------------
@bp.route("/v1/orders/<order_id>/stage", methods=["POST"])
def stage_order(order_id):
    user_id, role = get_user_context()
    require_role(role, {"Picker"})  # PRD §4: Picker only
    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        if order["fulfillment_status"] != "PICKING":
            err(ERR_INVALID_ORDER_STATE, "Order is not PICKING")
        lines = lookups.lines_for_order(order_id)
        # every line terminal; none PENDING
        if any(l["status"] == "PENDING" for l in lines):
            err(ERR_LINES_NOT_RESOLVED, "Some lines are still PENDING")
        # at least one PICKED or SUBSTITUTED
        if not any(l["status"] in ("PICKED", "SUBSTITUTED") for l in lines):
            err(ERR_NOTHING_TO_STAGE, "No line is PICKED or SUBSTITUTED")
        # --- commit ---
        order["staged_at"] = iso_now_ms(clock.now())  # current logical clock (PRD §3.5/§3.9)
        order["fulfillment_status"] = "STAGED"
        lookups.recompute_final_totals(order)
        db.touch(order)
        return object_response(_serialize(order))


# ---------------------------------------------------------------------------
# Capture (AUTHORIZED -> CAPTURED)
# ---------------------------------------------------------------------------
@bp.route("/v1/orders/<order_id>/capture", methods=["POST"])
def capture_order(order_id):
    user_id, role = get_user_context()
    require_role(role, {"StoreOps"})  # PRD §4: StoreOps only
    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        # payment must be AUTHORIZED (state, priority 5)
        if order["payment_status"] != "AUTHORIZED":
            err(ERR_INVALID_ORDER_STATE, "Payment is not AUTHORIZED")
        # order must be STAGED (priority 9 fiscal)
        if order["fulfillment_status"] != "STAGED":
            err(ERR_ORDER_NOT_STAGED, "Order is not STAGED")
        store = db.stores.get(order["store_id"])
        customer = db.customers.get(order["customer_id"])
        # ebt_enabled=false implies final_ebt_eligible_cents == 0
        if not store["ebt_enabled"] and order["final_ebt_eligible_cents"] != 0:
            err(ERR_EBT_NOT_ACCEPTED, "Store does not accept EBT but order has EBT-eligible value")
        # --- split-tender waterfall (PRD §3.6) ---
        ebt_charged, card_charged = calc.split_tender(
            order["final_ebt_eligible_cents"],
            customer["snap_ebt_balance_cents"],
            order["final_total_cents"],
        )
        order["ebt_charged_cents"] = ebt_charged
        order["card_charged_cents"] = card_charged
        # debit customer balance (not refilled by refunds in v1)
        customer["snap_ebt_balance_cents"] -= ebt_charged
        db.touch(customer)
        # create Payment record
        payment = {
            "order_id": order["id"],
            "ebt_amount_cents": ebt_charged,
            "card_amount_cents": card_charged,
            "grand_total_cents": ebt_charged + card_charged,
            "status": "CAPTURED",
        }
        db.stamp_create(payment)
        db.payments[payment["id"]] = payment
        order["payment_status"] = "CAPTURED"
        order["net_captured_cents"] = order["final_total_cents"]
        db.touch(order)
        return object_response(_serialize(order))


# ---------------------------------------------------------------------------
# Handoff (STAGED -> HANDED_OFF)
# ---------------------------------------------------------------------------
@bp.route("/v1/orders/<order_id>/handoff", methods=["POST"])
def handoff_order(order_id):
    user_id, role = get_user_context()
    require_role(role, {"StoreOps"})  # PRD §4: StoreOps only
    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        # STAGED required
        if order["fulfillment_status"] != "STAGED":
            err(ERR_ORDER_NOT_STAGED, "Order is not STAGED")
        # payment CAPTURED required
        if order["payment_status"] != "CAPTURED":
            err(ERR_PAYMENT_NOT_CAPTURED, "Payment is not CAPTURED")
        # --- priority 7: age gate ---
        if order["requires_age_check"]:
            checks = [a for a in db.age_checks.values() if a["order_id"] == order_id]
            if any(a["outcome"] == "FAIL" for a in checks):
                err(ERR_AGE_VERIFICATION_FAILED, "Age verification failed")
            if not any(a["outcome"] == "PASS" for a in checks):
                err(ERR_AGE_VERIFICATION_REQUIRED, "Age verification required")
        # --- priority 8: cold-chain gate ---
        lines = lookups.lines_for_order(order_id)
        has_cold = False
        for l in lines:
            if l["status"] not in ("PICKED", "SUBSTITUTED"):
                continue
            eff = calc.effective_product(l, lookups.product_lookup, lookups.accepted_sub_for_line)
            if eff and eff.get("cold_chain"):
                has_cold = True
                break
        if has_cold:
            store = db.stores.get(order["store_id"])
            staged_dt = parse_iso(order["staged_at"])
            expiry = staged_dt + timedelta(minutes=store["cold_chain_hold_minutes"])
            if not (clock.now() < expiry):
                err(ERR_COLD_CHAIN_EXPIRED, "Cold-chain hold window expired")
        # --- commit ---
        order["fulfillment_status"] = "HANDED_OFF"
        db.touch(order)
        return object_response(_serialize(order))


# ---------------------------------------------------------------------------
# Cancel ({PLACED,PICKING,STAGED} -> CANCELLED)
# ---------------------------------------------------------------------------
@bp.route("/v1/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer", "StoreOps"})  # PRD §4
    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        if not _customer_owns(role, user_id, order):
            err(ERR_FORBIDDEN_ROLE, "Customer may only cancel their own orders")
        # already HANDED_OFF cannot be cancelled
        if order["fulfillment_status"] == "HANDED_OFF":
            err(ERR_ORDER_ALREADY_HANDED_OFF, "Order already HANDED_OFF")
        if order["fulfillment_status"] not in ("PLACED", "PICKING", "STAGED"):
            err(ERR_INVALID_ORDER_STATE, "Order cannot be cancelled from its current state")
        # --- cascade 1: non-terminal lines -> CANCELLED, final 0 ---
        for l in lookups.lines_for_order(order_id):
            if l["status"] in ("PENDING", "PICKED", "SUBSTITUTED"):
                l["status"] = "CANCELLED"
                l["final_line_cents"] = 0
                db.touch(l)
        # --- cascade 2: release slot (booked_count -1, version +1; FULL->OPEN) ---
        slot = db.slots.get(order["slot_id"])
        if slot is not None:
            slot["booked_count"] -= 1
            if slot["status"] == "FULL" and slot["booked_count"] < slot["capacity"]:
                slot["status"] = "OPEN"
            db.touch(slot)
        # --- cascade 3: payment unwind ---
        if order["payment_status"] in ("CAPTURED", "PARTIALLY_REFUNDED"):
            order["payment_status"] = "REFUNDED"
            order["net_captured_cents"] = 0
        else:
            order["payment_status"] = "VOIDED"
        order["fulfillment_status"] = "CANCELLED"
        lookups.recompute_final_totals(order)
        db.touch(order)
        return object_response(_serialize(order))
