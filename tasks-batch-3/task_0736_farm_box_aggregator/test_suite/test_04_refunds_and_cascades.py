"""Refund waterfall, cancellation cascades, and conservation invariants.

Difficulty instances: transitive_cascade (short->refund->credit; cancel->line->offering),
compensating_invariant (offering-unit conservation; SNAP-cents conservation).
Corner instance: non-eligible short routes entirely to wallet.
"""
from test_helpers import (
    make_admin_headers,
    set_clock, new_farm, new_hub, new_customer, new_product, new_weight_product,
    new_cycle, new_offering, open_cycle, new_order, new_line, do_checkout, do_pack,
    cutoff_cycle,
    setup_open_egg_market, setup_snap_three_line_placed,
    assert_offering_conservation,
)


def _order(api, order_id):
    return api.get_order(order_id, make_admin_headers()).json()["data"]


def _customer(api, customer_id):
    return api.get_customer(customer_id, make_admin_headers()).json()["data"]


def _offering(api, offering_id):
    return api.get_offering(offering_id, make_admin_headers()).json()["data"]


def _line(api, line_id):
    return api.get_line(line_id, make_admin_headers()).json()["data"]


# ---------------------------------------------------------------------------
# transitive_cascade / short_line_refund_customer_credit_depth3
# ---------------------------------------------------------------------------
def test_short_line_records_partial_refund_on_order(api):
    """PRD §3.7: "The shortfall — the estimated line value minus the final line value — becomes
    a refund credit: the order's `refunded_snap_cents` and `refunded_wallet_cents` are updated
    per the refund waterfall in §3.8, the order's `payment_status` moves to `PARTIALLY_REFUNDED`,
    and the customer's `snap_balance_cents`, `doubleup_used_cents`, and `wallet_credit_cents` are
    adjusted accordingly."

    Design: Difficulty/transitive_cascade/short_line_refund_customer_credit_depth3
    """
    world = setup_snap_three_line_placed(api)
    cutoff_cycle(api, world["cycle"]["id"])
    packed = do_pack(api, world["farm"]["id"], world["line_tom"]["id"], fulfilled_qty=0, actual_weight_kg=0)
    assert packed["line_status"] == "SHORTED"
    assert packed["final_line_cents"] == 0
    order = _order(api, world["order"]["id"])
    # credit = 1200 estimated - 0 final; SNAP-first waterfall returns 800 to SNAP
    assert order["refunded_snap_cents"] == 800
    assert order["payment_status"] == "PARTIALLY_REFUNDED"


def test_short_line_credits_customer_snap_and_reverses_doubleup(api):
    """PRD §3.8: "The credited amounts then flow to the customer and the order: `snap_balance_cents`
    increases by the SNAP portion, `doubleup_used_cents` decreases by the Double-Up portion
    (reversing the earlier match), `wallet_credit_cents` increases by the wallet portion, the
    order's `refunded_snap_cents` increases by the SNAP portion, and the order's
    `refunded_wallet_cents` increases by the wallet portion."

    Design: Difficulty/transitive_cascade/short_line_refund_customer_credit_depth3
    """
    world = setup_snap_three_line_placed(api)
    cutoff_cycle(api, world["cycle"]["id"])
    do_pack(api, world["farm"]["id"], world["line_tom"]["id"], fulfilled_qty=0, actual_weight_kg=0)
    customer = _customer(api, world["customer"]["id"])
    # credit 1200: 800 to SNAP (0 -> 800), 400 reverses Double-Up (used 800 -> 400)
    assert customer["snap_balance_cents"] == 800
    assert customer["doubleup_used_cents"] == 400


# ---------------------------------------------------------------------------
# transitive_cascade / cancel_order_line_offering_release_depth2
# ---------------------------------------------------------------------------
def _placed_egg_order(api, requested_qty=2):
    world = setup_open_egg_market(api, snap_balance=0)
    order = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"])
    line = new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], requested_qty)
    do_checkout(api, world["customer"]["id"], order["id"])
    world["order"] = order
    world["line"] = line
    return world


def test_cancel_placed_order_cascades_to_line_and_refunds(api):
    """PRD §3.8: "Cancelling a `PLACED` or `ALLOCATED` order runs a full cascade: every
    non-terminal line moves to `CANCELLED`, and each such cancellation releases the line's
    `requested_qty` back to its offering's `reserved_qty` (with `remaining_qty` recomputed)."
    PRD §3.8: "The order's `payment_status` moves to `REFUNDED`."

    Design: Difficulty/transitive_cascade/cancel_order_line_offering_release_depth2
    """
    world = _placed_egg_order(api, requested_qty=2)
    api.cancel_order(world["order"]["id"], make_admin_headers())
    order = _order(api, world["order"]["id"])
    assert order["order_status"] == "CANCELLED"
    assert order["payment_status"] == "REFUNDED"
    assert _line(api, world["line"]["id"])["line_status"] == "CANCELLED"


def test_cancel_placed_order_releases_offering_reservation(api):
    """PRD §2.7: "When an order is cancelled, the cancellation cascades to its lines, and each
    cancelled line in turn releases its reserved units back to the offering."
    PRD §2.6: "The `remaining_qty` is `offered_qty` minus `reserved_qty` minus `committed_qty`."

    Design: Difficulty/transitive_cascade/cancel_order_line_offering_release_depth2
    """
    world = _placed_egg_order(api, requested_qty=2)
    api.cancel_order(world["order"]["id"], make_admin_headers())
    offering = _offering(api, world["offering"]["id"])
    assert offering["reserved_qty"] == 0
    assert offering["remaining_qty"] == 100


# ---------------------------------------------------------------------------
# compensating_invariant / offering_unit_conservation_add_then_cancel
# ---------------------------------------------------------------------------
def _cart_egg_line_qty4(api):
    world = setup_open_egg_market(api, snap_balance=0)
    order = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"])
    line = new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], 4)
    world["order"] = order
    world["line"] = line
    return world


def test_cancel_restores_offering_units_with_no_drift(api):
    """PRD §2.6: "The platform holds a conservation invariant at all times: an offering's
    `offered_qty` always equals the sum of its `remaining_qty`, `reserved_qty`, and
    `committed_qty`."
    PRD §2.7: "When an order is cancelled, the cancellation cascades to its lines, and each
    cancelled line in turn releases its reserved units back to the offering."

    Design: Difficulty/compensating_invariant/offering_unit_conservation_add_then_cancel
    """
    world = _cart_egg_line_qty4(api)
    api.cancel_order(world["order"]["id"], make_admin_headers())
    offering = _offering(api, world["offering"]["id"])
    assert offering["reserved_qty"] == 0
    assert offering["committed_qty"] == 0
    assert offering["remaining_qty"] == 100
    assert_offering_conservation(offering)


def test_cancel_cascades_reserving_line_to_cancelled(api):
    """PRD §2.7: "When an order is cancelled, the cancellation cascades to its lines, and each
    cancelled line in turn releases its reserved units back to the offering."

    Design: Difficulty/compensating_invariant/offering_unit_conservation_add_then_cancel
    """
    world = _cart_egg_line_qty4(api)
    api.cancel_order(world["order"]["id"], make_admin_headers())
    assert _line(api, world["line"]["id"])["line_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# compensating_invariant / snap_cents_conservation_checkout_then_cancel
# ---------------------------------------------------------------------------
def _snap_two_line_placed(api):
    """Customer snap 800; tomato (WEIGHT, snap-eligible) qty3 + egg (FIXED 400, snap-eligible)
    qty2; eligible subtotal 2000; checked out (snap_applied 800, doubleup_match 800, owed 400)."""
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=800)
    tomato = new_weight_product(api, farm["id"], name="Heirloom Tomatoes", category="PRODUCE",
                                price_per_kg_cents=800, estimated_weight_kg=0.5, snap_eligible=True)
    egg = new_product(api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=True)
    cycle = new_cycle(api)
    off_tom = new_offering(api, cycle["id"], farm["id"], tomato["id"], offered_qty=100)
    off_egg = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    new_line(api, customer["id"], order["id"], off_tom["id"], 3)
    new_line(api, customer["id"], order["id"], off_egg["id"], 2)
    do_checkout(api, customer["id"], order["id"])
    return {"customer": customer, "order": order}


def test_checkout_debits_snap_balance_and_doubleup(api):
    """PRD §3.6: "As side effects of checkout, the customer's `snap_balance_cents` is reduced by
    `snap_applied_cents` and their `doubleup_used_cents` is increased by `doubleup_match_cents`."

    Design: Difficulty/compensating_invariant/snap_cents_conservation_checkout_then_cancel
    """
    world = _snap_two_line_placed(api)
    customer = _customer(api, world["customer"]["id"])
    assert customer["snap_balance_cents"] == 0
    assert customer["doubleup_used_cents"] == 800


def test_full_cancel_conserves_snap_cents_to_pre_checkout(api):
    """PRD §3.8: "As a conservation guarantee, a checkout followed by a full refund returns the
    customer's `snap_balance_cents` to its exact pre-checkout value."
    PRD §3.8: "A full refund is then issued — the order's frozen `snap_applied_cents` is returned
    to the customer's `snap_balance_cents` and recorded in the order's `refunded_snap_cents`; the
    `doubleup_match_cents` is reversed out of the customer's `doubleup_used_cents`; and the order's
    `customer_owed_cents` is credited to the customer's `wallet_credit_cents` and recorded in the
    order's `refunded_wallet_cents`."

    Design: Difficulty/compensating_invariant/snap_cents_conservation_checkout_then_cancel
    """
    world = _snap_two_line_placed(api)
    api.cancel_order(world["order"]["id"], make_admin_headers())
    customer = _customer(api, world["customer"]["id"])
    assert customer["snap_balance_cents"] == 800, "SNAP restored to pre-checkout value"
    assert customer["doubleup_used_cents"] == 0, "Double-Up match reversed"
    assert customer["wallet_credit_cents"] == 400, "out-of-pocket returned as wallet credit"
    assert _order(api, world["order"]["id"])["payment_status"] == "REFUNDED"


# ---------------------------------------------------------------------------
# Corner: calculations / refund_to_wallet_for_non_eligible_short
# ---------------------------------------------------------------------------
def test_non_eligible_short_routes_entire_credit_to_wallet(api):
    """PRD §3.8: "If the line is not `snap_eligible`, the entire credit becomes wallet credit
    and nothing is returned to SNAP or Double-Up."

    Design: Corner/calculations/refund_to_wallet_for_non_eligible_short
    """
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    flower = new_product(api, farm["id"], name="Cut Flowers", category="OTHER", pricing_mode="FIXED",
                         unit_price_cents=500, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], flower["id"], offered_qty=50)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line = new_line(api, customer["id"], order["id"], offering["id"], 1)
    do_checkout(api, customer["id"], order["id"])
    cutoff_cycle(api, cycle["id"])

    packed = do_pack(api, farm["id"], line["id"], fulfilled_qty=0)
    assert packed["line_status"] == "SHORTED"
    assert packed["final_line_cents"] == 0
    cust = _customer(api, customer["id"])
    assert cust["wallet_credit_cents"] == 500
    assert cust["snap_balance_cents"] == 0
    order_after = _order(api, order["id"])
    assert order_after["refunded_wallet_cents"] == 500
    assert order_after["refunded_snap_cents"] == 0
