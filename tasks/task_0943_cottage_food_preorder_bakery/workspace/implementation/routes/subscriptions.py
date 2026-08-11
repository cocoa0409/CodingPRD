"""The bread-and-cookie club: memberships, cycles and the reserved share."""

from datetime import timedelta
from math import floor

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import capacity, cascade, money, pricing
from services.gates import (cutoff_gate, permit_gate, product_class_gate,
                            require_state, window_locked_gate,
                            window_open_gate)
from tsutil import dec, gte, lt, ts_shift

bp = Blueprint("subscriptions", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER


def cycles_of(subscription_id):
    return [c for c in DB.values("subscription_cycles")
            if c.get("subscription_id") == subscription_id]


@bp.post("/bakery/subscriptions")
@endpoint(roles=[CUSTOMER, BAKER])
def create_subscription(ctx):
    fks = ctx.body_fks(required=("menu_item_id", "customer_id"))   # rungs 9, 10
    item = fks["menu_item_id"]
    customer = fks["customer_id"]
    if item is None:
        raise ApiError("ERR_VALIDATION", "menu_item_id is required.")
    if customer is None:
        raise ApiError("ERR_VALIDATION", "customer_id is required.")
    ctx.ownership(customer_id=customer["id"],                      # rungs 11, 12
                  baker_id=item.get("baker_id"))
    units_per_cycle = ctx.req_int("units_per_cycle", minimum=0)    # rung 13
    for name in ("cadence", "billing_mode", "handoff_mode"):
        if ctx.body.get(name) is None:
            raise ApiError("ERR_VALIDATION", "%s is required." % name)
    cadence = ctx.enum("cadence", "cadence")                       # rung 14
    billing_mode = ctx.enum("billing_mode", "billing_mode")
    handoff_mode = ctx.enum("handoff_mode", "handoff_mode")
    permit_gate(DB.get("bakers", item.get("baker_id")))            # rung 15
    product_class_gate(item)                                      # rung 25

    rec = base_record(ctx.now)
    rec.update({
        "customer_id": customer["id"],
        "menu_item_id": item["id"],
        "cadence": cadence,
        "units_per_cycle": units_per_cycle,
        "billing_mode": billing_mode,
        "handoff_mode": handoff_mode,
        "sub_status": "PENDING",
        "pause_count": 0,
        "past_due_since": None,
        "prepaid_balance_cents": 0,
    })
    DB.coll("subscriptions")[rec["id"]] = rec
    return created(dump("subscriptions", rec))


@bp.post("/bakery/subscriptions/<subscription_id>/status")
@endpoint(roles=[CUSTOMER, BAKER], path=("subscription_id",))
def subscription_status(ctx):
    sub = ctx.p["subscription_id"]
    item = DB.get("menu_items", sub.get("menu_item_id"))
    ctx.ownership(customer_id=sub.get("customer_id"),             # rungs 11, 12
                  baker_id=(item or {}).get("baker_id"))
    if ctx.body.get("to_status") is None:                          # rung 13
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "sub_status")                # rung 14
    current = sub.get("sub_status")

    if to_status == "ACTIVE":                                      # rung 19
        require_state(current, ("PENDING", "PAUSED", "PAST_DUE"), "sub_status")
        if current == "PENDING":
            if (item or {}).get("listing_status") != "LISTED":
                raise ApiError("ERR_INVALID_STATE",
                               "Activation requires a LISTED club menu item.")
        if current == "PAST_DUE" and _has_unpaid_placed_cycle(sub):
            raise ApiError("ERR_INVALID_STATE",
                           "An arrears cycle is still unpaid.")
    elif to_status == "PAUSED":
        require_state(current, ("ACTIVE",), "sub_status")
        if (sub.get("pause_count") or 0) >= config.SUBSCRIPTION_PAUSE_CAP_COUNT:
            raise ApiError("ERR_PAUSE_CAP_EXCEEDED",               # rung 43
                           "The pause cap of %d has been reached."
                           % config.SUBSCRIPTION_PAUSE_CAP_COUNT)
    elif to_status == "PAST_DUE":
        require_state(current, ("ACTIVE",), "sub_status")
        if sub.get("billing_mode") != "PAY_PER_CYCLE":
            raise ApiError("ERR_INVALID_STATE",
                           "Only a PAY_PER_CYCLE membership falls into arrears.")
        if not _has_unpaid_placed_cycle(sub):
            raise ApiError("ERR_INVALID_STATE",
                           "No placed cycle has an unpaid order.")
    elif to_status == "CANCELLED":
        require_state(current, ("ACTIVE", "PAUSED", "PAST_DUE"), "sub_status")
        if current == "PAST_DUE":
            since = sub.get("past_due_since")
            if since is None or not gte(
                    ctx.now, ts_shift(since,
                                      timedelta(hours=config.PAST_DUE_GRACE_HOURS))):
                raise ApiError("ERR_INVALID_STATE",
                               "The %d-hour arrears grace has not elapsed."
                               % config.PAST_DUE_GRACE_HOURS)
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "%s is not reachable through this capability." % to_status)

    # ---- commit ---------------------------------------------------------
    touched_windows = set()
    if to_status == "ACTIVE":
        if current == "PENDING" and sub.get("billing_mode") == "PREPAID":
            price = pricing.cycle_price(sub, item)
            deposit = config.PREPAID_DEPOSIT_CYCLES * price
            money.create_movement(
                ctx.now,
                customer_id=sub.get("customer_id"),
                ledger_scope="SUBSCRIPTION_PREPAID",
                movement_kind="PREPAY_DEPOSIT",
                reason="SUBSCRIPTION_PREPAY",
                amount_cents=deposit,
                subscription_id=sub["id"],
            )
            money.refresh_prepaid_balance(sub)
        if current == "PAST_DUE":
            sub["past_due_since"] = None
    elif to_status == "PAUSED":
        sub["pause_count"] = (sub.get("pause_count") or 0) + 1
        for cyc in cycles_of(sub["id"]):
            if cyc.get("cycle_status") == "RESERVED":
                touched_windows.add(cyc.get("offer_window_id"))
                cascade.release_cycle(cyc, ctx.now)
    elif to_status == "PAST_DUE":
        sub["past_due_since"] = ctx.now
    else:  # CANCELLED
        for cyc in cycles_of(sub["id"]):
            if cyc.get("cycle_status") in ("GENERATED", "RESERVED"):
                touched_windows.add(cyc.get("offer_window_id"))
                cascade.release_cycle(cyc, ctx.now)
        if sub.get("billing_mode") == "PREPAID":
            remaining = money.prepaid_balance(sub["id"])
            if remaining > 0:
                money.create_movement(
                    ctx.now,
                    customer_id=sub.get("customer_id"),
                    ledger_scope="SUBSCRIPTION_PREPAID",
                    movement_kind="CREDIT_REDEEM",
                    reason="CUSTOMER_CANCEL",
                    amount_cents=-remaining,
                    subscription_id=sub["id"],
                )
                money.create_movement(
                    ctx.now,
                    customer_id=sub.get("customer_id"),
                    ledger_scope="CUSTOMER_CREDIT",
                    movement_kind="PREPAY_DEPOSIT",
                    reason="CUSTOMER_CANCEL",
                    amount_cents=remaining,
                    subscription_id=sub["id"],
                )
                money.refresh_prepaid_balance(sub)
                cust = DB.get("customers", sub.get("customer_id"))
                if cust is not None:
                    money.refresh_credit_balance(cust, ctx.now)
    sub["sub_status"] = to_status
    touch(sub, ctx.now)
    for wid in touched_windows:
        capacity.sync(DB.get("offer_windows", wid), ctx.now)
    return ok(dump("subscriptions", sub))


def _has_unpaid_placed_cycle(sub):
    for cyc in cycles_of(sub["id"]):
        if cyc.get("cycle_status") != "ORDER_PLACED":
            continue
        for order in DB.coll("orders").values():
            if (order.get("subscription_cycle_id") == cyc["id"]
                    and order.get("payment_status") == "UNPAID"):
                return True
    return False


# ---------------------------------------------------------------------------
# cycles
# ---------------------------------------------------------------------------

@bp.post("/bakery/subscriptions/<subscription_id>/cycles")
@endpoint(roles=[BAKER], path=("subscription_id",))
def generate_cycle(ctx):
    sub = ctx.p["subscription_id"]
    fks = ctx.body_fks(required=("offer_window_id",))              # rung 8
    window = fks["offer_window_id"]
    if window is None:
        raise ApiError("ERR_VALIDATION", "offer_window_id is required.")
    ctx.ownership(baker_id=window.get("baker_id"))                 # rung 12
    sequence_number = ctx.req_int("sequence_number", minimum=0)     # rung 13
    permit_gate(DB.get("bakers", window.get("baker_id")))          # rung 15
    window_locked_gate(window)                                     # rung 16
    window_open_gate(window)                                       # rung 18
    units = sub.get("units_per_cycle") or 0
    share_cap = int(floor(dec(window.get("capacity_units") or 0)
                          * dec(config.SUBSCRIPTION_RESERVE_UNIT_SHARE_PCT)))
    already = capacity.reserved_units(window["id"])
    if already + units > share_cap:                                # rung 52
        raise ApiError("ERR_SUBSCRIPTION_RESERVE_SHARE_EXCEEDED",
                       "The club share cap of %d units would be exceeded."
                       % share_cap)
    fig = capacity.figures(window, ctx.now)                        # rung 53
    if fig["units_remaining"] < units:
        raise ApiError("ERR_UNITS_CAPACITY_EXCEEDED",
                       "The window has %d orderable units left."
                       % fig["units_remaining"])

    item = DB.get("menu_items", sub.get("menu_item_id"))
    rec = base_record(ctx.now)
    rec.update({
        "subscription_id": sub["id"],
        "offer_window_id": window["id"],
        "sequence_number": sequence_number,
        "cycle_status": "GENERATED",
        "reserved_units": 0,
        "skip_deadline_at": None,
        "cycle_price_cents": 0,
    })
    DB.coll("subscription_cycles")[rec["id"]] = rec
    # GENERATED -> RESERVED inside the same request
    rec["cycle_status"] = "RESERVED"
    rec["reserved_units"] = units
    rec["skip_deadline_at"] = ts_shift(
        window["order_cutoff_at"],
        timedelta(hours=-config.SKIP_DEADLINE_HOURS_BEFORE_CUTOFF))
    rec["cycle_price_cents"] = pricing.cycle_price(sub, item)
    touch(rec, ctx.now)
    capacity.sync(window, ctx.now, force_bump=True)
    return created(dump("subscription_cycles", rec))


@bp.post("/bakery/subscription-cycles/<subscription_cycle_id>/skip")
@endpoint(roles=[CUSTOMER], path=("subscription_cycle_id",))
def skip_cycle(ctx):
    cyc = ctx.p["subscription_cycle_id"]
    sub = DB.get("subscriptions", cyc.get("subscription_id"))
    window = DB.get("offer_windows", cyc.get("offer_window_id"))
    ctx.ownership(customer_id=(sub or {}).get("customer_id"))       # rung 11
    window_locked_gate(window)                                      # rung 16
    require_state(cyc.get("cycle_status"), ("RESERVED",), "cycle_status")
    deadline = cyc.get("skip_deadline_at")                          # rung 40
    if deadline is None or not lt(ctx.now, deadline):
        raise ApiError("ERR_SKIP_DEADLINE_PASSED",
                       "The cycle skip deadline has passed.")
    cyc["cycle_status"] = "SKIPPED"
    cyc["reserved_units"] = 0
    touch(cyc, ctx.now)
    capacity.sync(window, ctx.now)
    return ok(dump("subscription_cycles", cyc))


@bp.post("/bakery/subscription-cycles/<subscription_cycle_id>/confirm")
@endpoint(roles=[CUSTOMER], path=("subscription_cycle_id",))
def confirm_cycle(ctx):
    cyc = ctx.p["subscription_cycle_id"]
    sub = DB.get("subscriptions", cyc.get("subscription_id"))
    window = DB.get("offer_windows", cyc.get("offer_window_id"))
    ctx.ownership(customer_id=(sub or {}).get("customer_id"))       # rung 11
    expected = ctx.req_int("expected_subscription_version", minimum=0)  # rung 13
    baker = DB.get("bakers", (window or {}).get("baker_id"))
    permit_gate(baker)                                              # rung 15
    window_locked_gate(window)                                      # rung 16
    cutoff_gate(window, ctx.now)                                    # rung 17
    window_open_gate(window)                                        # rung 18
    require_state(cyc.get("cycle_status"), ("RESERVED",), "cycle_status")
    if (sub or {}).get("sub_status") != "ACTIVE":                    # rung 19
        raise ApiError("ERR_INVALID_STATE",
                       "The membership is not ACTIVE.")
    if expected != sub.get("version"):                              # rung 23
        raise ApiError("ERR_STALE_SUBSCRIPTION_VERSION",
                       "expected_subscription_version is stale.")

    item = DB.get("menu_items", sub.get("menu_item_id"))
    customer = DB.get("customers", sub.get("customer_id"))
    units = sub.get("units_per_cycle") or 0
    _basis, total = pricing.line_total(item, units)
    _taxable, tax = pricing.line_tax("WHOLE_UNHEATED", total)
    distance = None
    fee = 0
    if sub.get("handoff_mode") == "DELIVERY":
        # delivery_distance_km must be set or route sequencing (which sorts on
        # it) could not order a club delivery order at all.
        distance = (customer or {}).get("delivery_distance_km")
        fee = pricing.delivery_fee("DELIVERY", distance, reject_out_of_zone=False)
    counted = total + tax + fee
    current_gross = money.annual_gross_sales(baker)                 # rung 51
    if current_gross + counted > (baker.get("annual_cap_cents") or 0):
        raise ApiError("ERR_ANNUAL_CAP_EXCEEDED",
                       "The annual gross-sales cap would be exceeded.")

    # ---- commit: RESERVED -> CONFIRMED -> ORDER_PLACED -------------------
    cyc["cycle_status"] = "CONFIRMED"
    prepaid = sub.get("billing_mode") == "PREPAID"
    order = base_record(ctx.now)
    order.update({
        "customer_id": sub.get("customer_id"),
        "offer_window_id": window["id"],
        "subscription_cycle_id": cyc["id"],
        "delivery_route_id": None,
        "channel": "DTC",
        "handoff_mode": sub.get("handoff_mode"),
        "source": "SUBSCRIPTION_CLUB",
        "prepaid": prepaid,
        "order_status": "CONFIRMED",
        "payment_status": "UNPAID",
        "handoff_status": "NOT_SCHEDULED",
        # Adjudication of friction 9: placed_at is the CURRENT INSTANT.  A null
        # placed_at would drop the club order out of the cap_year filter of PRD
        # 2.8, which would make the declared "recomputes annual_gross_sales_cents"
        # side effect of cycle confirmation a no-op and would leave rung 51's
        # declared application to club-cycle confirmation unreachable.
        "placed_at": ctx.now,
        "hold_expires_at": None,
        "allergen_ack": False,
        "unattended_consent": False,
        "cooler_provided": False,
        "delivery_distance_km": distance,
        "stop_sequence": None,
        "subtotal_cents": total,
        "tax_total_cents": tax,
        "delivery_fee_cents": fee,
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
    DB.coll("orders")[order["id"]] = order
    line = base_record(ctx.now)
    line.update({
        "order_id": order["id"],
        "menu_item_id": sub.get("menu_item_id"),
        "batch_id": None,
        "quantity": units,
        "disposition": "WHOLE_UNHEATED",
        "line_status": "PENDING",
        "allocated_units": 0,
        "shorted_units": 0,
        "allergen_union": [],
        "hold_expires_at": None,
    })
    from services import allergen as allergen_svc
    line["allergen_union"] = allergen_svc.union_only((item or {}).get("recipe_id"))
    pricing.price_line(line, item)
    DB.coll("order_lines")[line["id"]] = line

    if prepaid:
        price = cyc.get("cycle_price_cents") or 0
        money.create_movement(
            ctx.now,
            customer_id=sub.get("customer_id"),
            ledger_scope="SUBSCRIPTION_PREPAID",
            movement_kind="CREDIT_REDEEM",
            reason="ORDER_APPLY",
            amount_cents=-price,
            order_id=order["id"],
            subscription_id=sub["id"],
        )
        money.refresh_prepaid_balance(sub)
        order["credit_applied_cents"] = price
        # Adjudication of friction 10: a PREPAID club order's grand_total_cents
        # IS computed here, through the six pinned steps of PRD 3.9 with a tip of
        # 0 and the cycle price as applied credit.  Such an order never sees a
        # payment, so leaving the field at its default of 0 would make the pinned
        # computation unreachable for the whole PREPAID club path.  A
        # PAY_PER_CYCLE club order is left at 0 until its payment, because PRD
        # 3.9 pins the grand total to payment authorisation and this friction is
        # declared for the PREPAID case alone.
        order["grand_total_cents"] = total + tax + fee + 0 - price
    cyc["cycle_status"] = "ORDER_PLACED"
    touch(cyc, ctx.now)
    touch(sub, ctx.now)
    money.refresh_gross_sales(baker)
    touch(baker, ctx.now)
    capacity.sync(window, ctx.now)
    return ok(dump("subscription_cycles", cyc))


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

@bp.get("/bakery/subscriptions/<subscription_id>")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("subscription_id",))
def read_subscription(ctx):
    sub = ctx.p["subscription_id"]
    item = DB.get("menu_items", sub.get("menu_item_id"))
    ctx.ownership(customer_id=sub.get("customer_id"),
                  baker_id=(item or {}).get("baker_id"))
    return ok(dump("subscriptions", sub))


@bp.get("/bakery/subscriptions")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], list_ep=True)
def list_subscriptions(ctx):
    return list_endpoint(ctx, "subscriptions", {
        "customer_id": "customer_id",
        "menu_item_id": "menu_item_id",
        "sub_status": "sub_status",
        "billing_mode": "billing_mode",
    })


@bp.get("/bakery/subscription-cycles/<subscription_cycle_id>")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], path=("subscription_cycle_id",))
def read_cycle(ctx):
    cyc = ctx.p["subscription_cycle_id"]
    sub = DB.get("subscriptions", cyc.get("subscription_id"))
    window = DB.get("offer_windows", cyc.get("offer_window_id"))
    ctx.ownership(customer_id=(sub or {}).get("customer_id"),
                  baker_id=(window or {}).get("baker_id"))
    return ok(dump("subscription_cycles", cyc))


@bp.get("/bakery/subscription-cycles")
@endpoint(roles=[CUSTOMER, BAKER, ADMIN], list_ep=True)
def list_cycles(ctx):
    return list_endpoint(ctx, "subscription_cycles", {
        "subscription_id": "subscription_id",
        "offer_window_id": "offer_window_id",
        "cycle_status": "cycle_status",
    })
