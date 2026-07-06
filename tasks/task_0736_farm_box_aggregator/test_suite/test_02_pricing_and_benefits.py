"""Estimated-vs-final pricing and SNAP/Double-Up benefit application.

Difficulty instances: dual_variant_calc (line + order), combinatorial_formula (mode a),
boundary_precision_check (Double-Up cap).
"""
from test_helpers import (
    make_customer_headers,
    set_clock, new_farm, new_hub, new_customer, new_product, new_weight_product,
    new_cycle, new_offering, open_cycle, new_order, new_line, do_checkout, do_pack,
    do_fulfill, cutoff_cycle,
    setup_snap_three_line_cart, setup_snap_three_line_placed,
)


# ---------------------------------------------------------------------------
# dual_variant_calc / line_pricing_estimated_vs_final_weight
# ---------------------------------------------------------------------------
def _tomato_single_line(api):
    """One WEIGHT tomato line (price_per_kg 800, est_weight 0.5) of qty 3 in a CART order."""
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=800)
    tomato = new_weight_product(api, farm["id"], name="Heirloom Tomatoes", category="PRODUCE",
                                price_per_kg_cents=800, estimated_weight_kg=0.5, snap_eligible=True)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], tomato["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line = new_line(api, customer["id"], order["id"], offering["id"], 3)
    return {"farm": farm, "customer": customer, "cycle": cycle, "order": order, "line": line}


def test_weight_line_estimated_price_at_line_add(api):
    """PRD §3.5: "For a `WEIGHT` product, `estimated_line_cents` is the `requested_qty`
    multiplied by the product's `estimated_weight_kg` and by the effective per-kilogram price,
    rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/line_pricing_estimated_vs_final_weight
    """
    world = _tomato_single_line(api)
    # 3 units * 0.5 kg/unit * 800 cents/kg == 1200
    assert world["line"]["estimated_line_cents"] == 1200


def test_weight_line_final_price_and_delta_at_pack(api):
    """PRD §3.7: "For a `WEIGHT` line, `final_line_cents` is the recorded total
    `actual_weight_kg` multiplied by the effective per-kilogram price, rounded half up to
    whole cents once."
    PRD §3.7: "The final price is computed by the final pricing rule below, `price_delta_cents`
    is set to `final_line_cents` minus `estimated_line_cents`, the offering's `reserved_qty`
    decreases by the line's `requested_qty` while its `committed_qty` increases by `fulfilled_qty`."

    Design: Difficulty/dual_variant_calc/line_pricing_estimated_vs_final_weight
    """
    world = _tomato_single_line(api)
    do_checkout(api, world["customer"]["id"], world["order"]["id"])
    cutoff_cycle(api, world["cycle"]["id"])
    packed = do_pack(api, world["farm"]["id"], world["line"]["id"], fulfilled_qty=3, actual_weight_kg=1.7)
    # 1.7 kg * 800 cents/kg == 1360; delta 1360 - 1200 == 160
    assert packed["final_line_cents"] == 1360
    assert packed["price_delta_cents"] == 160
    assert packed["line_status"] == "PACKED"


# ---------------------------------------------------------------------------
# dual_variant_calc / order_owed_estimated_vs_final_reconciliation
# ---------------------------------------------------------------------------
def test_order_owed_estimated_variant_at_checkout(api):
    """PRD §3.6: "`customer_owed_cents` is the subtotal minus `snap_applied_cents` minus
    `doubleup_match_cents`, but never less than zero."

    Design: Difficulty/dual_variant_calc/order_owed_estimated_vs_final_reconciliation
    """
    world = setup_snap_three_line_cart(api)
    checkout = do_checkout(api, world["customer"]["id"], world["order"]["id"])
    # subtotal 2500 - snap 800 - doubleup 800 == 900
    assert checkout["customer_owed_cents"] == 900


def test_order_owed_final_variant_after_fulfill(api):
    """PRD §3.8: "At fulfillment the order's `final_total_cents` is set to the sum of its
    lines' `final_line_cents`, and `customer_owed_cents` is recomputed in the final variant of
    the benefit rule: the frozen `snap_applied_cents` and `doubleup_match_cents` are left
    untouched, only the gross is refreshed to `final_total_cents`, so `customer_owed_cents`
    becomes `final_total_cents` minus the frozen SNAP minus the frozen Double-Up, never less
    than zero."

    Design: Difficulty/dual_variant_calc/order_owed_estimated_vs_final_reconciliation
    """
    world = setup_snap_three_line_placed(api)
    cutoff_cycle(api, world["cycle"]["id"])
    do_pack(api, world["farm"]["id"], world["line_tom"]["id"], fulfilled_qty=3, actual_weight_kg=1.7)
    do_pack(api, world["farm"]["id"], world["line_egg"]["id"], fulfilled_qty=2)
    do_pack(api, world["farm"]["id"], world["line_flower"]["id"], fulfilled_qty=1)
    fulfilled = do_fulfill(api, world["order"]["id"])
    # final gross: tomato 1360 + egg 800 + flower 500 == 2660; owed 2660 - 800 - 800 == 1060
    assert fulfilled["final_total_cents"] == 2660
    assert fulfilled["customer_owed_cents"] == 1060
    assert fulfilled["snap_applied_cents"] == 800, "SNAP stays frozen at its checkout value"
    assert fulfilled["doubleup_match_cents"] == 800, "Double-Up stays frozen at its checkout value"


# ---------------------------------------------------------------------------
# combinatorial_formula / benefit_application_nested_min_max_mode_a
# ---------------------------------------------------------------------------
def test_benefit_application_breakdown_at_checkout(api):
    """PRD §3.6: "`eligible_subtotal_cents` is the sum of `estimated_line_cents` over only
    those lines whose `snap_eligible` is true."
    PRD §3.6: "`snap_applied_cents` is the smaller of the customer's `snap_balance_cents` and
    `eligible_subtotal_cents`."
    PRD §3.6: "`doubleup_match_cents` is the smaller of `snap_applied_cents` and the customer's
    remaining Double-Up headroom, where headroom is the Double-Up cap of 2000 cents ($20) minus
    the customer's current `doubleup_used_cents`, and headroom is never treated as less than zero."

    Design: Difficulty/combinatorial_formula/benefit_application_nested_min_max_mode_a
    """
    world = setup_snap_three_line_cart(api)
    checkout = do_checkout(api, world["customer"]["id"], world["order"]["id"])
    assert checkout["eligible_subtotal_cents"] == 2000, "tomato 1200 + egg 800 (flower excluded)"
    assert checkout["snap_applied_cents"] == 800, "min(snap_balance 800, eligible 2000)"
    assert checkout["doubleup_match_cents"] == 800, "min(snap 800, headroom 2000)"
    assert checkout["customer_owed_cents"] == 900, "max(0, 2500 - 800 - 800)"


def test_checkout_consumes_snap_and_increments_doubleup_used(api):
    """PRD §3.6: "As side effects of checkout, the customer's `snap_balance_cents` is reduced
    by `snap_applied_cents` and their `doubleup_used_cents` is increased by `doubleup_match_cents`."

    Design: Difficulty/combinatorial_formula/benefit_application_nested_min_max_mode_a
    """
    world = setup_snap_three_line_cart(api)
    do_checkout(api, world["customer"]["id"], world["order"]["id"])
    customer = api.get_customer(world["customer"]["id"], make_customer_headers(world["customer"]["id"])).json()["data"]
    assert customer["snap_balance_cents"] == 0, "800 balance - 800 applied == 0"
    assert customer["doubleup_used_cents"] == 800, "0 + 800 match == 800"


# ---------------------------------------------------------------------------
# boundary_precision_check / doubleup_cap_zero_match_at_exact_cap
# ---------------------------------------------------------------------------
def _doubleup_cap_world(api):
    """Customer snap 5000; snap-eligible egg offering. Order1 buys 5 eggs (eligible 2000)
    and checks out (Double-Up match 2000 fills the cap). Order2 buys 2 eggs, left in CART."""
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=5000)
    egg = new_product(api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=True)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=100)
    open_cycle(api, cycle["id"])

    order1 = new_order(api, customer["id"], cycle["id"], hub["id"])
    new_line(api, customer["id"], order1["id"], offering["id"], 5)
    checkout1 = do_checkout(api, customer["id"], order1["id"])

    order2 = new_order(api, customer["id"], cycle["id"], hub["id"])
    new_line(api, customer["id"], order2["id"], offering["id"], 2)
    return {"customer": customer, "order1": order1, "order2": order2, "checkout1": checkout1}


def test_doubleup_match_fills_cap_on_first_order(api):
    """PRD §3.6: "`doubleup_match_cents` is the smaller of `snap_applied_cents` and the
    customer's remaining Double-Up headroom, where headroom is the Double-Up cap of 2000 cents
    ($20) minus the customer's current `doubleup_used_cents`, and headroom is never treated as
    less than zero."

    Design: Difficulty/boundary_precision_check/doubleup_cap_zero_match_at_exact_cap
    """
    world = _doubleup_cap_world(api)
    assert world["checkout1"]["doubleup_match_cents"] == 2000, "min(snap 2000, headroom 2000)"
    customer = api.get_customer(world["customer"]["id"], make_customer_headers(world["customer"]["id"])).json()["data"]
    assert customer["doubleup_used_cents"] == 2000, "Double-Up used now sits exactly at the cap"


def test_doubleup_match_zero_at_exact_cap_on_second_order(api):
    """PRD §3.6: "`doubleup_match_cents` is the smaller of `snap_applied_cents` and the
    customer's remaining Double-Up headroom, where headroom is the Double-Up cap of 2000 cents
    ($20) minus the customer's current `doubleup_used_cents`, and headroom is never treated as
    less than zero."
    PRD §3.6: "`snap_applied_cents` is the smaller of the customer's `snap_balance_cents` and
    `eligible_subtotal_cents`."

    Design: Difficulty/boundary_precision_check/doubleup_cap_zero_match_at_exact_cap
    """
    world = _doubleup_cap_world(api)
    checkout2 = do_checkout(api, world["customer"]["id"], world["order2"]["id"])
    # headroom = max(0, 2000 - 2000) == 0 -> match 0; snap still min(3000, 800) == 800
    assert checkout2["doubleup_match_cents"] == 0
    assert checkout2["snap_applied_cents"] == 800
