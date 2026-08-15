"""Order pricing variants, expedite fee stacking, and rounding tests."""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_product, create_branch, create_customer, create_branch_stock,
    create_order_with_line, create_confirmed_order_with_line,
    create_active_contract, publish_price_file, reserve_line, allocate_line,
    set_clock, get_order, get_order_line,
    ApiErrorId, TEST_USERS,
)

ANALYST = TEST_USERS["pricing_analyst_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
REP = TEST_USERS["counter_sales_rep_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_dual_variant_scenario():
    """Product BRG-6205 list 10000; branch; customer; stock 100.

    o1 (ORDER_DATE) confirmed/reserved/allocated at 2026-08-10;
    price file 10000 -> 12000 EFFECTIVE 2026-08-15;
    o2 (SHIP_DATE) confirmed/reserved/allocated at 2026-08-16.
    """
    set_clock("2026-08-10T10:00:00Z")
    product = create_product(sku="BRG-6205", list_price_cents=10000)
    branch = create_branch(code="ATL-01")
    customer = create_customer(name="Peach State Plant")
    stock = create_branch_stock(branch["id"], product["id"], on_hand_qty=100)

    o1, l1 = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=2,
        price_variant="ORDER_DATE")
    reserve_line(l1["id"], stock["id"], 2)
    l1 = allocate_line(l1["id"])

    publish_price_file(product["id"], 12000, "2026-08-15T00:00:00Z")
    set_clock("2026-08-16T00:00:00Z")

    o2, l2 = create_confirmed_order_with_line(
        customer["id"], branch["id"], product["id"], qty=2,
        price_variant="SHIP_DATE")
    reserve_line(l2["id"], stock["id"], 2)
    l2 = allocate_line(l2["id"])
    return {"product": product, "branch": branch, "customer": customer,
            "stock": stock, "o1": o1, "l1": l1, "o2": o2, "l2": l2}


def test_order_date_variant_locks_price_at_order_creation(api):
    """PRD §3.4: "The two order variants differ only in the anchor: for
    `ORDER_DATE`, T is the order's `created_at` and the price is locked at
    confirm, never recomputed at ship".

    Design: Difficulty/dual_variant_calc/order_line_order_date_vs_ship_date_price
    """
    ctx = _setup_dual_variant_scenario()
    set_clock("2026-08-20T10:00:00Z")
    line1 = get_success_data(api.ship_line(ctx["l1"]["id"], MANAGER))
    assert line1["unit_price_cents"] == 10000, (
        f"ORDER_DATE anchors at order creation (before the 2026-08-15 increase); "
        f"expected 10000, got {line1['unit_price_cents']}")
    assert line1["price_protection_applied"] is False
    order1 = get_order(ctx["o1"]["id"])
    assert order1["total_cents"] == 20000
    assert order1["fulfillment_status"] == "SHIPPED"


def test_ship_date_variant_reprices_at_ship_instant(api):
    """PRD §3.4: "for `SHIP_DATE`, T is now at confirm or reprice (provisional)
    and then each line's `shipped_at` at ship (final) — the two anchors may
    straddle a price-file effective instant and yield different unit prices for
    identical line data."

    Design: Difficulty/dual_variant_calc/order_line_order_date_vs_ship_date_price
    """
    ctx = _setup_dual_variant_scenario()
    # Provisional price at confirm (2026-08-16, after the increase) is 12000.
    line2_at_confirm = get_order_line(ctx["l2"]["id"])
    assert line2_at_confirm["unit_price_cents"] == 12000
    set_clock("2026-08-20T10:00:00Z")
    line2 = get_success_data(api.ship_line(ctx["l2"]["id"], MANAGER))
    assert line2["unit_price_cents"] == 12000, (
        f"SHIP_DATE anchors at the ship instant (after the increase); "
        f"expected 12000, got {line2['unit_price_cents']}")
    order2 = get_order(ctx["o2"]["id"])
    assert order2["total_cents"] == 24000
    assert order2["fulfillment_status"] == "SHIPPED"


def _setup_lag_protected_rush_order():
    """Contract LIST_LESS 10% lag 30; price file 10000->12000 EFFECTIVE 08-15;
    RUSH order (qty 10) created/confirmed at 2026-08-16T15:00 (after cutoff 14)."""
    set_clock("2026-08-01T09:00:00Z")
    product = create_product(sku="BRG-6206", list_price_cents=10000)
    branch = create_branch(code="CHI-03")
    customer = create_customer(name="Windy City Plant")
    create_active_contract(
        customer["id"], family="BEARING", price_basis="LIST_LESS",
        discount_pct=0.10, lag_protection_days=30,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")
    publish_price_file(product["id"], 12000, "2026-08-15T00:00:00Z")
    set_clock("2026-08-16T15:00:00Z")
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=10, expedite_tier="RUSH")
    return order, line


def test_lag_protection_pins_unit_price_below_post_increase_list(api):
    """PRD §3.4: "if a contract is present and its `lag_protection_days` exceeds
    0 and the product's `last_price_change_at` is not null and T falls before
    `last_price_change_at` plus the lag days, and the most recent change was an
    increase ... then recompute the candidate exactly as in step three but with
    the pre-increase price in place of the list price at T; if that protected
    candidate is lower, it wins and `price_protection_applied` is set true".

    Design: Difficulty/combinatorial_formula/expedite_fee_stacking_with_lag_protection
    """
    order, line = _setup_lag_protected_rush_order()
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    priced = get_order_line(line["id"])
    assert priced["unit_price_cents"] == 9000, (
        f"protected: round_half_up(10000 * 0.9) = 9000 (unprotected would be "
        f"10800); got {priced['unit_price_cents']}")
    assert priced["price_protection_applied"] is True
    assert confirmed["fulfillment_status"] == "CONFIRMED"


def test_expedite_fee_stacks_pct_cutoff_multiplier_and_floor(api):
    """PRD §3.4: "Start with the protected amount: the line's post-lag
    `unit_price_cents` times `qty`. The percentage portion by tier is ... 8
    percent of the protected amount rounded half-up for `RUSH` ... If the local
    hour at confirm is at or after the branch's `expedite_cutoff_hour` and the
    tier is `RUSH` or `EMERGENCY`, the percentage portion alone is multiplied by
    1.25 and rounded half-up again — the flat portion is never touched by the
    multiplier. ... The fee is the flat plus the percentage portion, then floored
    at the tier minimum: 2500 cents for `RUSH`".

    Design: Difficulty/combinatorial_formula/expedite_fee_stacking_with_lag_protection
    """
    order, line = _setup_lag_protected_rush_order()
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    priced = get_order_line(line["id"])
    # 8% of protected 90000 = 7200; after-cutoff x1.25 = 9000; >= 2500 floor.
    assert priced["expedite_fee_cents"] == 9000, (
        f"expected fee 9000 (7200 * 1.25), got {priced['expedite_fee_cents']}")
    assert priced["line_total_cents"] == 99000
    assert confirmed["subtotal_cents"] == 90000
    assert confirmed["expedite_fees_cents"] == 9000
    assert confirmed["total_cents"] == 99000


def _setup_rounding_order():
    """Products 3333 / 1111; contract LIST_LESS 10% (no lag); lines qty 3 + qty 1."""
    set_clock("2026-08-01T09:00:00Z")
    p1 = create_product(sku="BLT-A100", list_price_cents=3333)
    p2 = create_product(sku="BLT-B50", list_price_cents=1111)
    branch = create_branch(code="SEA-04")
    customer = create_customer(name="Emerald City Plant")
    create_active_contract(
        customer["id"], family="BEARING", price_basis="LIST_LESS",
        discount_pct=0.10, lag_protection_days=0,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")
    order = get_success_data(api_client.create_order(
        {"customer_id": customer["id"], "branch_id": branch["id"]}, REP))
    l1 = get_success_data(api_client.add_order_line(
        order["id"], {"product_id": p1["id"], "qty": 3}, REP))
    l2 = get_success_data(api_client.add_order_line(
        order["id"], {"product_id": p2["id"], "qty": 1}, REP))
    return order, l1, l2


def test_per_line_unit_prices_round_half_up_before_quantities(api):
    """PRD §3.4: "with a `LIST_LESS` contract the candidate is the list price at
    T multiplied by one minus `discount_pct`, rounded half-up to integer cents".
    PRD §2.7: "every rounding is round-half-up".

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_order_total
    """
    order, l1, l2 = _setup_rounding_order()
    validate_success(api.confirm_order(order["id"], REP), 200)
    line1 = get_order_line(l1["id"])
    line2 = get_order_line(l2["id"])
    assert line1["unit_price_cents"] == 3000, (
        f"round_half_up(3333 * 0.9) = round_half_up(2999.7) = 3000; "
        f"got {line1['unit_price_cents']}")
    assert line1["line_total_cents"] == 9000
    assert line2["unit_price_cents"] == 1000, (
        f"round_half_up(1111 * 0.9) = round_half_up(999.9) = 1000; "
        f"got {line2['unit_price_cents']}")
    assert line2["line_total_cents"] == 1000


def test_order_total_sums_per_line_rounded_amounts(api):
    """PRD §3.4: "**Order totals** aggregate with per-line-first rounding: each
    line's goods amount is its `unit_price_cents` times `qty`, rounded half-up
    (already integer cents unless a discount produced fractions upstream)".
    PRD §3.4: "Sum-then-round at the order level is forbidden."

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_order_total
    """
    order, l1, l2 = _setup_rounding_order()
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    # Per-line first: 3000*3 + 1000*1 = 10000; sum-then-round would give 9999.
    assert confirmed["subtotal_cents"] == 10000, (
        f"per-line rounding then sum must give 10000, got {confirmed['subtotal_cents']}")
    assert confirmed["total_cents"] == 10000


def test_standard_expedite_flat_fee_immune_to_cutoff(api):
    """PRD §3.4: "The percentage portion by tier is zero for `NONE`, zero for
    `STANDARD` (flat-only) ... The flat portion is zero except for `STANDARD`,
    where it is 1500 cents." and "the flat portion is never touched by the
    multiplier."

    Design: Corner/calculations/standard_expedite_flat_fee_immune_to_cutoff
    """
    set_clock("2026-08-03T15:00:00Z")  # local 15:00, at/after cutoff 14
    product = create_product(sku="BRG-6024", list_price_cents=10000)
    branch = create_branch(code="STD-14")
    customer = create_customer(name="Standard Plant")
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=2, expedite_tier="STANDARD")
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    priced = get_order_line(line["id"])
    assert priced["expedite_fee_cents"] == 1500, (
        f"STANDARD is flat-only 1500 even after cutoff; got {priced['expedite_fee_cents']}")
    assert confirmed["total_cents"] == 21500


def test_emergency_tier_minimum_clamp_fires(api):
    """PRD §3.4: "The fee is the flat plus the percentage portion, then floored
    at the tier minimum: 2500 cents for `RUSH`, 5000 cents for `EMERGENCY`, no
    floor for `NONE` or `STANDARD`."

    Design: Corner/calculations/emergency_tier_minimum_clamp_fires
    """
    set_clock("2026-08-03T09:00:00Z")  # local 09:00, before cutoff
    product = create_product(sku="BRG-6025", list_price_cents=1000)
    branch = create_branch(code="EMG-15")
    customer = create_customer(name="Emergency Plant")
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=1, expedite_tier="EMERGENCY")
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    priced = get_order_line(line["id"])
    # 15% of 1000 = 150, below the 5000 floor -> clamp fires.
    assert priced["expedite_fee_cents"] == 5000, (
        f"max(150, 5000) floor clamp must give 5000, got {priced['expedite_fee_cents']}")
    assert confirmed["total_cents"] == 6000


def test_contract_fixed_basis_pins_price_against_list_increase(api):
    """PRD §3.4: "with a `CONTRACT_FIXED` contract the candidate is
    `fixed_unit_price_cents`" and "Whenever any of these conditions fails,
    `price_protection_applied` is false."

    Design: Corner/calculations/contract_fixed_basis_pins_price_against_list_increase
    """
    set_clock("2026-08-01T09:00:00Z")
    product = create_product(sku="BRG-6060", list_price_cents=10000)
    branch = create_branch(code="FIX-40")
    customer = create_customer(name="Fixed Price Plant")
    create_active_contract(
        customer["id"], family="BEARING", price_basis="CONTRACT_FIXED",
        fixed_unit_price_cents=7000, lag_protection_days=30,
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z")
    publish_price_file(product["id"], 15000, "2026-08-05T00:00:00Z")
    order, line = create_order_with_line(
        customer["id"], branch["id"], product["id"], qty=2)
    set_clock("2026-08-06T09:00:00Z")  # price file now EFFECTIVE
    confirmed = validate_success(api.confirm_order(order["id"], REP), 200)
    priced = get_order_line(line["id"])
    assert priced["unit_price_cents"] == 7000, (
        f"CONTRACT_FIXED ignores the EFFECTIVE 15000 list; got {priced['unit_price_cents']}")
    assert priced["price_protection_applied"] is False
    assert confirmed["total_cents"] == 14000
