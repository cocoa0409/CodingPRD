"""Orders: opening, the hold, lines, re-pricing, confirmation and cancellation."""

from datetime import timedelta

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from serialize import dump
from services import allergen, capacity, cascade, money, pricing
from services.gates import (active_payment, dtc_gate, permit_gate,
                            product_class_gate, recipe_published_gate,
                            require_state, window_locked_gate, cutoff_gate,
                            window_open_gate)
from tsutil import lt, ts_shift

bp = Blueprint("orders", __name__)

BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER

LIVE_LINE_STATES_EXCLUDED = ("RELEASED", "RECALL_VOID")


def lines_of(order_id):
    return [l for l in DB.values("order_lines") if l.get("order_id") == order_id]


def live_lines(order_id):
    return [l for l in lines_of(order_id)
            if l.get("line_status") not in LIVE_LINE_STATES_EXCLUDED]


def baker_of(order):
    return money.baker_of_order(order)


# ---------------------------------------------------------------------------
# POST /bakery/orders
# ---------------------------------------------------------------------------

@bp.post("/bakery/orders")
@endpoint(roles=[CUSTOMER, BAKER])
def create_order(ctx):
    fks = ctx.body_fks(required=("offer_window_id", "customer_id"))  # rungs 8,10
    window = fks["offer_window_id"]
    customer = fks["customer_id"]
    if window is None:
        raise ApiError("ERR_VALIDATION", "offer_window_id is required.")
    if customer is None:
        raise ApiError("ERR_VALIDATION", "customer_id is required.")
    ctx.ownership(customer_id=customer["id"],                       # rungs 11,12
                  baker_id=window.get("baker_id"))
    if ctx.body.get("handoff_mode") is None:                        # rung 13
        raise ApiError("ERR_VALIDATION", "handoff_mode is required.")
    allergen_ack = ctx.opt_bool("allergen_ack", False)
    # Adjudication of friction 6: INFORMATIONAL ONLY -- the customer's standing
    # unattended_consent / cooler_provided are never inherited as order
    # defaults; the order's own flags are the sole gate rungs 31 and 32 read.
    # Inheritance would make the combination "standing consent true, order flag
    # false" unreachable (an omitted optional flag is indistinguishable from an
    # explicit false), and with it the rung-31/32 rejections for such a
    # customer.  Treating them as informational keeps all four combinations of
    # (standing flag, order flag) reachable and strands nothing.
    unattended = ctx.opt_bool("unattended_consent", False)
    cooler = ctx.opt_bool("cooler_provided", False)
    handoff_mode = ctx.enum("handoff_mode", "handoff_mode")          # rung 14
    channel = ctx.enum("channel", "channel", required=False, default="DTC")
    permit_gate(DB.get("bakers", window.get("baker_id")))            # rung 15
    window_locked_gate(window)                                      # rung 16
    window_open_gate(window)                                        # rung 18
    dtc_gate(channel)                                               # rung 24

    rec = base_record(ctx.now)
    rec.update({
        "customer_id": customer["id"],
        "offer_window_id": window["id"],
        "subscription_cycle_id": None,
        "delivery_route_id": None,
        "channel": channel,
        "handoff_mode": handoff_mode,
        "source": "WALKUP",
        "prepaid": False,
        "order_status": "DRAFT",
        "payment_status": "UNPAID",
        "handoff_status": "NOT_SCHEDULED",
        "placed_at": None,
        "hold_expires_at": None,
        "allergen_ack": allergen_ack,
        "unattended_consent": unattended,
        "cooler_provided": cooler,
        "delivery_distance_km": None,
        "stop_sequence": None,
        "subtotal_cents": 0,
        "tax_total_cents": 0,
        "delivery_fee_cents": 0,
        "tip_cents": 0,
        "credit_applied_cents": 0,
        "grand_total_cents": 0,
        "shortfall_flag": False,
        "rebook_count": 0,
        "pickup_forfeit_at": None,
        "forfeit_latched": False,
        "fulfilled_at": None,
        "review_window_closes_at": None,
        "review_window_closed_latch": False,
    })
    DB.coll("orders")[rec["id"]] = rec
    return created(dump("orders", rec))


# ---------------------------------------------------------------------------
# POST /bakery/orders/{order_id}/lines
# ---------------------------------------------------------------------------

@bp.post("/bakery/orders/<order_id>/lines")
@endpoint(roles=[CUSTOMER, BAKER], path=("order_id",))
def add_line(ctx):
    order = ctx.p["order_id"]
    fks = ctx.body_fks(required=("menu_item_id",))                  # rung 9
    item = fks["menu_item_id"]
    if item is None:
        raise ApiError("ERR_VALIDATION", "menu_item_id is required.")
    window = DB.get("offer_windows", order.get("offer_window_id"))
    ctx.ownership(customer_id=order.get("customer_id"),             # rungs 11,12
                  baker_id=(window or {}).get("baker_id"))
    quantity = ctx.req_int("quantity", minimum=0)                   # rung 13
    expected = ctx.req_int("expected_offer_window_version", minimum=0)
    disposition = ctx.enum("disposition", "disposition",            # rung 14
                           required=False, default="WHOLE_UNHEATED")
    permit_gate(DB.get("bakers", window.get("baker_id")))           # rung 15
    window_locked_gate(window)                                      # rung 16
    cutoff_gate(window, ctx.now)                                    # rung 17
    window_open_gate(window)                                        # rung 18
    require_state(order.get("order_status"),                        # rung 19
                  ("DRAFT", "PENDING_HOLD", "EXPIRED_HOLD"), "order_status")
    if expected != window.get("version"):                           # rung 20
        raise ApiError("ERR_STALE_OFFER_WINDOW_VERSION",
                       "expected_offer_window_version is stale.")
    product_class_gate(item)                                        # rung 25
    recipe = DB.get("recipes", item.get("recipe_id"))
    recipe_published_gate(recipe)                                   # rung 26
    if allergen.closure_recalled(item.get("recipe_id")):            # rung 27
        raise ApiError("ERR_LOT_RECALLED",
                       "The item's recipe closure contains a recalled component.")
    if len(live_lines(order["id"])) + 1 > config.MAX_LINES_PER_ORDER:   # rung 34
        raise ApiError("ERR_MAX_LINES_EXCEEDED",
                       "An order carries at most %d live lines."
                       % config.MAX_LINES_PER_ORDER)
    if quantity < config.MIN_UNITS_PER_LINE or quantity > config.MAX_UNITS_PER_LINE:
        raise ApiError("ERR_MAX_LINES_EXCEEDED",
                       "quantity must be between %d and %d."
                       % (config.MIN_UNITS_PER_LINE, config.MAX_UNITS_PER_LINE))
    _capacity_rungs(window, ctx.now, item["id"], quantity)          # rungs 53-55

    # ---- commit ---------------------------------------------------------
    first_hold = order.get("order_status") in ("DRAFT", "EXPIRED_HOLD")
    if first_hold:
        order["order_status"] = "PENDING_HOLD"
        order["placed_at"] = ctx.now
        order["hold_expires_at"] = ts_shift(
            ctx.now, timedelta(minutes=config.HOLD_TTL_MINUTES))
    line = base_record(ctx.now)
    line.update({
        "order_id": order["id"],
        "menu_item_id": item["id"],
        "batch_id": None,
        "quantity": quantity,
        "disposition": disposition,
        "line_status": "PENDING",
        "allocated_units": 0,
        "shorted_units": 0,
        "allergen_union": allergen.union_only(item.get("recipe_id")),
        "hold_expires_at": order.get("hold_expires_at"),
    })
    pricing.price_line(line, item)
    DB.coll("order_lines")[line["id"]] = line
    touch(order, ctx.now)
    capacity.sync(window, ctx.now, force_bump=True)
    return created(dump("order_lines", line))


def _capacity_rungs(window, now, item_id, delta_units):
    """Rungs 53, 54, 55 in that fixed order."""
    if delta_units <= 0:
        return
    fig = capacity.figures(window, now)
    if fig["units_remaining"] < delta_units:                        # rung 53
        raise ApiError("ERR_UNITS_CAPACITY_EXCEEDED",
                       "The window has %d orderable units left."
                       % fig["units_remaining"])
    after = capacity.figures(window, now, extra_item=item_id,
                             extra_units=delta_units)
    extra_slots = after["slots_used"] - fig["slots_used"]
    if fig["batch_slots_remaining"] < extra_slots:                  # rung 54
        raise ApiError("ERR_BATCH_SLOT_CAPACITY_EXCEEDED",
                       "The window has %d batch slots left."
                       % fig["batch_slots_remaining"])
    extra_oven = after["oven_hours_used_exact"] - fig["oven_hours_used_exact"]
    if fig["oven_hours_remaining_exact"] < extra_oven:              # rung 55
        raise ApiError("ERR_OVEN_HOURS_CAPACITY_EXCEEDED",
                       "The window has %s oven hours left."
                       % fig["oven_hours_remaining"])


# ---------------------------------------------------------------------------
# PATCH /bakery/orders/{order_id}/lines/{order_line_id}
# ---------------------------------------------------------------------------

@bp.patch("/bakery/orders/<order_id>/lines/<order_line_id>")
@endpoint(roles=[CUSTOMER, BAKER], path=("order_id", "order_line_id"))
def patch_line(ctx):
    order = ctx.p["order_id"]
    line = ctx.p["order_line_id"]
    if line.get("order_id") != order["id"]:                         # rung 6
        raise ApiError("ERR_ORDER_NOT_FOUND",
                       "order_line_id does not belong to this order.")
    window = DB.get("offer_windows", order.get("offer_window_id"))
    ctx.ownership(customer_id=order.get("customer_id"),             # rungs 11,12
                  baker_id=(window or {}).get("baker_id"))
    quantity = ctx.req_int("quantity", minimum=0)                   # rung 13
    expected = ctx.req_int("expected_offer_window_version", minimum=0)
    disposition = ctx.enum("disposition", "disposition",            # rung 14
                           required=False, default=line.get("disposition"))
    permit_gate(DB.get("bakers", window.get("baker_id")))           # rung 15
    window_locked_gate(window)                                      # rung 16
    cutoff_gate(window, ctx.now)                                    # rung 17
    window_open_gate(window)                                        # rung 18
    require_state(line.get("line_status"), ("PENDING",), "line_status")  # rung 19
    if expected != window.get("version"):                           # rung 20
        raise ApiError("ERR_STALE_OFFER_WINDOW_VERSION",
                       "expected_offer_window_version is stale.")
    if len(live_lines(order["id"])) > config.MAX_LINES_PER_ORDER:    # rung 34
        raise ApiError("ERR_MAX_LINES_EXCEEDED",
                       "An order carries at most %d live lines."
                       % config.MAX_LINES_PER_ORDER)
    if quantity < config.MIN_UNITS_PER_LINE or quantity > config.MAX_UNITS_PER_LINE:
        raise ApiError("ERR_MAX_LINES_EXCEEDED",
                       "quantity must be between %d and %d."
                       % (config.MIN_UNITS_PER_LINE, config.MAX_UNITS_PER_LINE))
    hold = order.get("hold_expires_at")                             # rung 38
    if hold is None or not lt(ctx.now, hold):
        raise ApiError("ERR_HOLD_EXPIRED", "The order's hold has expired.")
    delta = quantity - (line.get("quantity") or 0)
    _capacity_rungs(window, ctx.now, line.get("menu_item_id"), delta)  # 53-55

    item = DB.get("menu_items", line.get("menu_item_id"))
    line["quantity"] = quantity
    line["disposition"] = disposition
    # re-pricing from scratch: under PER_DOZEN_BAKERS a quantity REDUCTION can
    # raise line_total_cents (12 -> 5400, 13 -> 4600).
    pricing.price_line(line, item)
    touch(line, ctx.now)
    capacity.sync(window, ctx.now, force_bump=True)
    return ok(dump("order_lines", line))


# ---------------------------------------------------------------------------
# POST /bakery/orders/{order_id}/confirm
# ---------------------------------------------------------------------------

@bp.post("/bakery/orders/<order_id>/confirm")
@endpoint(roles=[CUSTOMER], path=("order_id",))
def confirm_order(ctx):
    order = ctx.p["order_id"]
    window = DB.get("offer_windows", order.get("offer_window_id"))
    ctx.ownership(customer_id=order.get("customer_id"))             # rung 11
    ack_field = ctx.opt_bool("allergen_ack", None)                  # rung 13
    baker = DB.get("bakers", window.get("baker_id"))
    permit_gate(baker)                                              # rung 15
    window_locked_gate(window)                                      # rung 16
    cutoff_gate(window, ctx.now)                                    # rung 17
    window_open_gate(window)                                        # rung 18
    require_state(order.get("order_status"), ("PENDING_HOLD",), "order_status")
    pending = [l for l in lines_of(order["id"])
               if l.get("line_status") == "PENDING"]
    if not pending:                                                 # rung 19
        raise ApiError("ERR_INVALID_STATE",
                       "The order has no PENDING line to confirm.")
    dtc_gate(order.get("channel"))                                  # rung 24

    customer = DB.get("customers", order.get("customer_id"))
    ack = order.get("allergen_ack") if ack_field is None else ack_field
    _allergen_gate(pending, customer, ack)                          # rungs 29,30

    if order.get("handoff_mode") == "DELIVERY":                     # rung 33
        distance = (customer or {}).get("delivery_distance_km")
        radius = (baker or {}).get("permitted_radius_km")
        if distance is None or radius is None or float(distance) > float(radius):
            raise ApiError("ERR_OUT_OF_PERMITTED_ZONE",
                           "The delivery distance leaves the permitted radius.")
    hold = order.get("hold_expires_at")                             # rung 38
    if hold is None or not lt(ctx.now, hold):
        raise ApiError("ERR_HOLD_EXPIRED", "The order's hold has expired.")

    # price into temporaries so a rung-51 rejection mutates nothing
    priced = []
    subtotal = 0
    tax_total = 0
    for line in lines_of(order["id"]):
        if line.get("line_status") in LIVE_LINE_STATES_EXCLUDED:
            continue
        item = DB.get("menu_items", line.get("menu_item_id"))
        basis, total = pricing.line_total(item, line.get("quantity") or 0)
        taxable, tax = pricing.line_tax(line.get("disposition"), total)
        priced.append((line, basis, taxable, total, tax))
        subtotal += total
        if line.get("line_status") == "PENDING":
            tax_total += tax
    distance = None
    if order.get("handoff_mode") == "DELIVERY":
        distance = (customer or {}).get("delivery_distance_km")
    fee = pricing.delivery_fee(order.get("handoff_mode"), distance)

    counted = subtotal + tax_total + fee                            # rung 51
    current_gross = money.annual_gross_sales(baker)
    if current_gross + counted > (baker.get("annual_cap_cents") or 0):
        raise ApiError("ERR_ANNUAL_CAP_EXCEEDED",
                       "The annual gross-sales cap would be exceeded.")

    # ---- commit ---------------------------------------------------------
    for line, basis, taxable, total, tax in priced:
        line["pricing_basis_applied"] = basis
        line["taxable"] = taxable
        line["line_total_cents"] = total
        line["line_tax_cents"] = tax
    order["order_status"] = "CONFIRMED"
    order["subtotal_cents"] = subtotal
    order["tax_total_cents"] = tax_total
    order["delivery_fee_cents"] = fee
    order["delivery_distance_km"] = distance
    order["hold_expires_at"] = None
    if ack_field is not None:
        order["allergen_ack"] = ack_field
    touch(order, ctx.now)

    money.refresh_gross_sales(baker)
    baker_dirty = True
    # PRD 3.1: the confirm that crosses the ceiling SUCCEEDS; the crossing
    # latches the gate for the NEXT confirm.
    if (baker.get("permit_status") == "ACTIVE"
            and baker["annual_gross_sales_cents"] >= (baker.get("annual_cap_cents") or 0)):
        baker["permit_status"] = "CAP_REACHED"
    if baker_dirty:
        touch(baker, ctx.now)
    capacity.sync(window, ctx.now)
    return ok(dump("orders", order))


def _allergen_gate(pending_lines, customer, ack):
    """calculations.allergen_gate -- rung 29 then rung 30."""
    order_allergens = set()
    for line in pending_lines:
        for a in line.get("allergen_union") or []:
            order_allergens.add(a)
    hard = set()
    soft = set()
    for entry in (customer or {}).get("allergen_avoidances") or []:
        name = (entry.get("allergen") or "").lower()
        if entry.get("severity") == config.ALLERGEN_SEVERITY_HARD_BLOCK:
            hard.add(name)
        elif entry.get("severity") == config.ALLERGEN_SEVERITY_ACK_REQUIRED:
            soft.add(name)
    if hard & order_allergens:                                       # rung 29
        raise ApiError("ERR_ALLERGEN_HARD_BLOCK",
                       "An order allergen matches an ANAPHYLACTIC avoidance.")
    if (soft & order_allergens) and ack is not True:                 # rung 30
        raise ApiError("ERR_ALLERGEN_ACK_REQUIRED",
                       "An allergen acknowledgement is required.")


# ---------------------------------------------------------------------------
# POST /bakery/orders/{order_id}/cancel
# ---------------------------------------------------------------------------

@bp.post("/bakery/orders/<order_id>/cancel")
@endpoint(roles=[CUSTOMER, BAKER], path=("order_id",))
def cancel_order(ctx):
    # CARVE-OUT: rung 15 never applies -- cancellation stays reachable while
    # the operator's permit is suspended.
    order = ctx.p["order_id"]
    window = DB.get("offer_windows", order.get("offer_window_id"))
    ctx.ownership(customer_id=order.get("customer_id"),
                  baker_id=(window or {}).get("baker_id"))
    ctx.opt_str("cancel_reason")                                    # rung 13
    window_locked_gate(window)                                      # rung 16
    current = order.get("order_status")                             # rung 19
    require_state(current, ("PENDING_HOLD", "EXPIRED_HOLD", "CONFIRMED"),
                  "order_status")
    if current == "CONFIRMED":
        if window.get("window_status") != "OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "A CONFIRMED order may only be cancelled while the "
                           "window is OPEN.")
        if not lt(ctx.now, window["order_cutoff_at"]):
            raise ApiError("ERR_INVALID_STATE",
                           "A CONFIRMED order may only be cancelled before the "
                           "cutoff.")

    cascade.release_pending_lines(order, ctx.now)
    order["order_status"] = "CANCELLED"
    order["hold_expires_at"] = None
    _unwind_money(order, ctx.now)
    touch(order, ctx.now)

    baker = DB.get("bakers", window.get("baker_id"))
    if baker is not None:
        money.refresh_gross_sales(baker)
        money.refresh_payout_net(baker)
        touch(baker, ctx.now)
    capacity.sync(window, ctx.now)
    return ok(dump("orders", order))


def _unwind_money(order, now):
    pay = active_payment(order["id"])
    if pay is None:
        return
    state = pay.get("payment_state")
    if state == "AUTHORIZED":
        pay["payment_state"] = "VOIDED"
        touch(pay, now)
        order["payment_status"] = "VOIDED"
        applied = order.get("credit_applied_cents") or 0
        if applied > 0:
            money.create_movement(
                now,
                customer_id=order.get("customer_id"),
                ledger_scope="CUSTOMER_CREDIT",
                movement_kind="PREPAY_DEPOSIT",
                reason="CUSTOMER_CANCEL",
                amount_cents=applied,
                order_id=order["id"],
                payment_id=pay["id"],
            )
            cust = DB.get("customers", order.get("customer_id"))
            if cust is not None:
                money.refresh_credit_balance(cust, now)
    elif state == "CAPTURED":
        amount = money.refundable_remainder(pay)
        if amount > 0:
            legs = money.waterfall(order, amount)
            money.create_movement(
                now,
                customer_id=order.get("customer_id"),
                ledger_scope="SETTLEMENT",
                movement_kind="REFUND",
                reason="CUSTOMER_CANCEL",
                amount_cents=amount,
                order_id=order["id"],
                payment_id=pay["id"],
                legs=legs,
            )
            pay["refunded_cents"] = (pay.get("refunded_cents") or 0) + amount
            touch(pay, now)
        order["payment_status"] = "REFUNDED"
