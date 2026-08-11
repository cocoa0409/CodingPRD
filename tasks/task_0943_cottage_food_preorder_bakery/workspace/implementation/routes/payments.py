"""Payments: authorisation, the pinned six-step total, capture and refunds."""

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import money, pricing
from services.gates import permit_gate, require_state
from tsutil import dec

bp = Blueprint("payments", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER


@bp.post("/bakery/payments")
@endpoint(roles=[CUSTOMER])
def create_payment(ctx):
    fks = ctx.body_fks(required=("order_id",))                      # rung 10
    order = fks["order_id"]
    if order is None:
        raise ApiError("ERR_VALIDATION", "order_id is required.")
    ctx.ownership(customer_id=order.get("customer_id"))             # rung 11
    if ctx.body.get("tip_mode") is None:                            # rung 13
        raise ApiError("ERR_VALIDATION", "tip_mode is required.")
    tip_pct = ctx.opt_num("tip_pct")
    tip_fixed_cents = ctx.opt_int("tip_fixed_cents", minimum=0)
    apply_credit_cents = ctx.opt_int("apply_credit_cents", minimum=0)
    tip_mode = ctx.enum("tip_mode", "tip_mode")                     # rung 14
    outcome = ctx.enum("outcome", "outcome", required=False, default="SUCCEEDED")
    window = DB.get("offer_windows", order.get("offer_window_id"))
    baker = DB.get("bakers", (window or {}).get("baker_id"))
    permit_gate(baker)                                              # rung 15
    require_state(order.get("payment_status"), ("UNPAID",), "payment_status")
    require_state(order.get("order_status"),                         # rung 19
                  ("CONFIRMED", "IN_PRODUCTION", "READY"), "order_status")
    # rung 46
    if tip_mode == "PERCENT":
        if tip_pct is None:
            raise ApiError("ERR_TIP_OUT_OF_RANGE", "tip_pct is required.")
        if dec(tip_pct) < 0 or dec(tip_pct) > dec(config.TIP_PCT_MAX):
            raise ApiError("ERR_TIP_OUT_OF_RANGE",
                           "tip_pct must be between 0 and %s." % config.TIP_PCT_MAX)
    else:
        if tip_fixed_cents is None:
            raise ApiError("ERR_TIP_OUT_OF_RANGE", "tip_fixed_cents is required.")
        if tip_fixed_cents > config.TIP_FIXED_MAX_CENTS:
            raise ApiError("ERR_TIP_OUT_OF_RANGE",
                           "tip_fixed_cents must be at most %d."
                           % config.TIP_FIXED_MAX_CENTS)
    customer = DB.get("customers", order.get("customer_id"))
    balance = money.credit_balance(order.get("customer_id"), ctx.now)
    if customer is not None:
        customer["credit_balance_cents"] = balance
    if apply_credit_cents is not None and apply_credit_cents > balance:  # rung 48
        raise ApiError("ERR_INSUFFICIENT_CREDIT",
                       "apply_credit_cents exceeds the customer's balance.")

    # ---- the pinned six-step evaluation order (PRD 3.9) -------------------
    # step 1: price every PENDING line
    for line in pricing.order_lines(order["id"]):
        if line.get("line_status") != "PENDING":
            continue
        item = DB.get("menu_items", line.get("menu_item_id"))
        if item is not None:
            pricing.price_line(line, item)
    # step 2
    subtotal = pricing.order_subtotal(order["id"])
    tax_total = pricing.order_tax_total(order["id"])
    # step 3
    fee = pricing.delivery_fee(order.get("handoff_mode"),
                               order.get("delivery_distance_km"))
    # step 4 -- base is the SUBTOTAL alone
    tip = pricing.tip_amount(tip_mode, tip_pct, tip_fixed_cents, subtotal)
    # step 5 -- the cap deliberately EXCLUDES the tip
    eligible = subtotal + tax_total + fee
    # Adjudication of friction 3: applied = lesser-of(REQUESTED, eligible),
    # with an omitted apply_credit_cents meaning zero.  This strictly dominates
    # the lesser-of(balance, eligible) reading on reachability: setting
    # apply_credit_cents to the whole balance reproduces that reading exactly,
    # while the balance-driven reading makes the state "customer holds credit
    # AND the order applied none of it" unreachable, since every payment would
    # silently consume the balance.  Rung 48 has already capped the request at
    # the balance, so the PRD's "lesser of the buyer's available balance and the
    # eligible portion" still holds.
    requested = apply_credit_cents or 0
    credit_applied = requested if requested < eligible else eligible
    if credit_applied > balance:
        credit_applied = balance
    # step 6
    grand_total = subtotal + tax_total + fee + tip - credit_applied

    pay = base_record(ctx.now)
    pay.update({
        "order_id": order["id"],
        "payment_state": "INITIATED",
        "outcome": outcome,
        "tip_mode": tip_mode,
        "tip_pct": tip_pct,
        "tip_fixed_cents": tip_fixed_cents,
        "tip_cents": tip,
        "authorized_cents": 0,
        "captured_cents": 0,
        "refunded_cents": 0,
    })
    DB.coll("payments")[pay["id"]] = pay

    if outcome == "DECLINED":
        # a decline leaves the order's money axis at UNPAID so a further
        # payment may be attempted; the order's money fields are not written,
        # because the transition that writes them is UNPAID -> AUTHORIZED.
        pay["payment_state"] = "DECLINED"
        return created(dump("payments", pay))

    pay["payment_state"] = "AUTHORIZED"
    pay["authorized_cents"] = grand_total
    order["subtotal_cents"] = subtotal
    order["tax_total_cents"] = tax_total
    order["delivery_fee_cents"] = fee
    order["tip_cents"] = tip
    order["credit_applied_cents"] = credit_applied
    order["grand_total_cents"] = grand_total
    order["payment_status"] = "AUTHORIZED"
    touch(order, ctx.now)
    if credit_applied > 0:
        money.create_movement(
            ctx.now,
            customer_id=order.get("customer_id"),
            ledger_scope="CUSTOMER_CREDIT",
            movement_kind="CREDIT_REDEEM",
            reason="ORDER_APPLY",
            amount_cents=-credit_applied,
            order_id=order["id"],
            payment_id=pay["id"],
        )
        if customer is not None:
            money.refresh_credit_balance(customer, ctx.now)
    return created(dump("payments", pay))


@bp.post("/bakery/payments/<payment_id>/capture")
@endpoint(roles=[BAKER], path=("payment_id",))
def capture_payment(ctx):
    pay = ctx.p["payment_id"]
    order = DB.get("orders", pay.get("order_id"))
    window = DB.get("offer_windows", (order or {}).get("offer_window_id"))
    ctx.ownership(baker_id=(window or {}).get("baker_id"))          # rung 12
    require_state(pay.get("payment_state"), ("AUTHORIZED",), "payment_state")
    require_state((order or {}).get("payment_status"), ("AUTHORIZED",),
                  "payment_status")
    require_state((order or {}).get("order_status"),                 # rung 19
                  ("CONFIRMED", "IN_PRODUCTION", "READY"), "order_status")
    pay["payment_state"] = "CAPTURED"
    pay["captured_cents"] = pay.get("authorized_cents") or 0
    touch(pay, ctx.now)
    order["payment_status"] = "CAPTURED"
    touch(order, ctx.now)
    baker = DB.get("bakers", (window or {}).get("baker_id"))
    if baker is not None:
        money.refresh_payout_net(baker)
        touch(baker, ctx.now)
    return ok(dump("payments", pay))


@bp.post("/bakery/payments/<payment_id>/refunds")
@endpoint(roles=[BAKER], path=("payment_id",))
def create_refund(ctx):
    # CARVE-OUT: rung 15 never applies -- refunds stay reachable while the
    # permit is suspended.  Rung 19 does not apply either: rung 49 owns the
    # payment-state precondition exclusively, so ERR_PAYMENT_NOT_CAPTURED stays
    # reachable (the same shape as rung 36's carve-out on yield confirmation).
    pay = ctx.p["payment_id"]
    order = DB.get("orders", pay.get("order_id"))
    window = DB.get("offer_windows", (order or {}).get("offer_window_id"))
    ctx.ownership(baker_id=(window or {}).get("baker_id"))          # rung 12
    amount = ctx.req_int("amount_cents", minimum=0)                  # rung 13
    ctx.req_str("refund_reason")
    expected = ctx.req_int("expected_order_version", minimum=0)
    if order is None or expected != order.get("version"):            # rung 21
        raise ApiError("ERR_STALE_ORDER_VERSION",
                       "expected_order_version is stale.")
    if pay.get("payment_state") != "CAPTURED":                       # rung 49
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED",
                       "The payment is %s." % pay.get("payment_state"))
    remainder = money.refundable_remainder(pay)
    if amount > remainder:                                           # rung 50
        raise ApiError("ERR_REFUND_EXCEEDS_CAPTURED",
                       "At most %d cents remain refundable." % remainder)

    legs = money.waterfall(order, amount)
    # `reason` is a system enum whose five members name the cascades that write
    # movements; a baker-initiated refund matches none of them, so it is left
    # null.  The caller's free-text refund_reason has no declared storage field.
    movement = money.create_movement(
        ctx.now,
        customer_id=order.get("customer_id"),
        ledger_scope="SETTLEMENT",
        movement_kind="REFUND",
        reason=None,
        amount_cents=amount,
        order_id=order["id"],
        payment_id=pay["id"],
        legs=legs,
    )
    pay["refunded_cents"] = (pay.get("refunded_cents") or 0) + amount
    touch(pay, ctx.now)
    order["payment_status"] = ("REFUNDED"
                               if money.refundable_remainder(pay) == 0
                               else "PARTIALLY_REFUNDED")
    touch(order, ctx.now)
    baker = DB.get("bakers", (window or {}).get("baker_id"))
    if baker is not None:
        money.refresh_gross_sales(baker)
        money.refresh_payout_net(baker)
        touch(baker, ctx.now)
    cust = DB.get("customers", order.get("customer_id"))
    if cust is not None:
        money.refresh_credit_balance(cust, ctx.now)
    return created(dump("money_movements", movement))


@bp.get("/bakery/payments/<payment_id>")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("payment_id",))
def read_payment(ctx):
    pay = ctx.p["payment_id"]
    order = DB.get("orders", pay.get("order_id"))
    window = DB.get("offer_windows", (order or {}).get("offer_window_id"))
    ctx.ownership(customer_id=(order or {}).get("customer_id"),
                  baker_id=(window or {}).get("baker_id"))
    return ok(dump("payments", pay))


@bp.get("/bakery/payments")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], list_ep=True)
def list_payments(ctx):
    return list_endpoint(ctx, "payments", {
        "order_id": "order_id",
        "payment_state": "payment_state",
    })


@bp.get("/bakery/money-movements/<money_movement_id>")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("money_movement_id",))
def read_movement(ctx):
    return ok(dump("money_movements", ctx.p["money_movement_id"]))


@bp.get("/bakery/money-movements")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], list_ep=True)
def list_movements(ctx):
    return list_endpoint(ctx, "money_movements", {
        "customer_id": "customer_id",
        "order_id": "order_id",
        "payment_id": "payment_id",
        "subscription_id": "subscription_id",
        "movement_kind": "movement_kind",
        "reason": "reason",
        "ledger_scope": "ledger_scope",
    })
