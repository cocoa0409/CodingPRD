"""Pricing engine: estimated vs final variants, bulk split, per-line rounding.

Covers the dual-variant calculation and combinatorial-formula difficulty rules,
plus the estimate / deposit calculation corners.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    ensure_pricing_policy,
    create_cut_type,
    create_customer,
    receive_lot,
    place_and_confirm_order,
    setup_holiday_window_before_cutoff,
    place_holiday_order,
    TEST_USERS,
    api_client,
)

MGR = TEST_USERS["shift_manager_headers"]
CLERK = TEST_USERS["counter_clerk_headers"]
BUTCHER = TEST_USERS["butcher_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc / orderline_estimate_vs_final_catch_weight_price
# ===========================================================================
def test_estimate_and_final_diverge_on_same_line(api):
    """PRD §3.4: "The **estimated** variant prices an order line at the moment
    the order is placed, using the line's `ordered_weight_g` and applying **no
    shrink**."
    PRD §3.4: "Billable grams are the catch weight times one-minus-the-shrink-fraction,
    floored to a whole number of grams."

    Estimate: 2000g * (4000/1000) = 8000c. Final: floor(2000*0.96)=1920g * 4.0 = 7680c.

    Design: Difficulty/dual_variant_calc/orderline_estimate_vs_final_catch_weight_price
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Stan Standard", phone="555-0001")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 2000)])
    line = get_success_data(api.get_order_line(line_ids[0], CLERK))
    assert line["est_line_cents"] == 8000, f"est expected 8000, got {line['est_line_cents']}"

    lot = receive_lot(cut["id"], received_weight_g=5000)
    drawn = validate_success(
        api.draw_line(
            line_ids[0],
            {"drawn_lot_id": lot["id"], "catch_weight_g": 2000,
             "expected_inventory_lot_version": lot["version"]},
            BUTCHER,
        )
    )
    assert drawn["final_line_cents"] == 7680, f"final expected 7680, got {drawn['final_line_cents']}"
    assert drawn["est_line_cents"] == 8000


def test_final_line_price_applies_shrink_before_pricing(api):
    """PRD §3.4: "Billable grams are the catch weight times
    one-minus-the-shrink-fraction, floored to a whole number of grams."
    PRD §3.4: "the result is rounded half up to whole cents to produce the line's
    `final_line_cents`."

    Catch 2000g, whole-cut shrink 0.04 -> billable 1920g -> 7680c; this must
    differ from the unshrunk estimate of 8000c.

    Design: Difficulty/dual_variant_calc/orderline_estimate_vs_final_catch_weight_price
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Stan Standard", phone="555-0001")
    order, line_ids = place_and_confirm_order(cust["id"], [(cut["id"], 2000)])
    lot = receive_lot(cut["id"], received_weight_g=5000)
    drawn = validate_success(
        api.draw_line(
            line_ids[0],
            {"drawn_lot_id": lot["id"], "catch_weight_g": 2000,
             "expected_inventory_lot_version": lot["version"]},
            BUTCHER,
        )
    )
    assert drawn["final_line_cents"] == 7680
    assert drawn["final_line_cents"] != drawn["est_line_cents"], (
        "final (catch-weight, shrunk) must diverge from estimate (ordered-weight)"
    )


# ===========================================================================
# Difficulty: combinatorial_formula / bulk_tier_nonlinear_wholesale_split
# ===========================================================================
def test_bulk_tier_wholesale_nonlinear_split(api):
    """PRD §3.4: "The bulk portion is priced as its grams times the per-gram rate
    times one-minus-the-tier-fraction and then additionally times
    one-minus-the-`bulk_extra_discount_pct`, so the bulk discount stacks
    multiplicatively on top of the tier discount and applies only to the bulk grams."

    WHOLESALE 8000g, base 1200, threshold 5000: normal 5000*1.2*0.8=4800,
    bulk 3000*1.2*0.8*0.95=2736, total 7536.

    Design: Difficulty/combinatorial_formula/bulk_tier_nonlinear_wholesale_split
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="GROUND_CHUCK", species="BEEF",
                          base_price_cents_per_kg=1200, is_grind=True)
    cust = create_customer(full_name="Wanda Wholesale", phone="555-0002",
                           loyalty_tier="WHOLESALE")
    order = get_success_data(
        api.create_custom_order(
            {"customer_id": cust["id"], "order_kind": "STANDARD",
             "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 8000}]},
            CLERK,
        )
    )
    assert order["estimated_total_cents"] == 7536, (
        f"expected 7536, got {order['estimated_total_cents']}"
    )


def test_bulk_threshold_inclusive_at_boundary_gram(api):
    """PRD §3.4: "the threshold boundary is inclusive, so the gram at exactly the
    threshold counts as bulk."

    WHOLESALE line of exactly bulk_threshold_g (5000g): bulk_g = 5000-5000... the
    gram at the threshold counts as bulk, so bulk_g = 0 grams below threshold are
    normal. Concretely ordered 5000g: bulk_g = 5000-5000 = 0; normal_g = 5000.
    normal 5000*1.2*0.8 = 4800c; no bulk grams -> total 4800c.

    Design: Difficulty/combinatorial_formula/bulk_tier_nonlinear_wholesale_split
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="GROUND_CHUCK", species="BEEF",
                          base_price_cents_per_kg=1200, is_grind=True)
    cust = create_customer(full_name="Wendy Boundary", phone="555-0022",
                           loyalty_tier="WHOLESALE")
    order = get_success_data(
        api.create_custom_order(
            {"customer_id": cust["id"], "order_kind": "STANDARD",
             "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 5000}]},
            CLERK,
        )
    )
    # ordered_weight_g (5000) >= threshold (5000): grams from threshold upward =
    # 5000-5000 = 0 bulk grams; all 5000 normal -> 5000*1.2*0.8 = 4800c.
    assert order["estimated_total_cents"] == 4800, (
        f"expected 4800, got {order['estimated_total_cents']}"
    )


# ===========================================================================
# Difficulty: combinatorial_formula / per_line_round_then_sum_ordering
# ===========================================================================
def test_per_line_round_then_sum(api):
    """PRD §3.4: "An order's `estimated_total_cents` is the sum of `est_line_cents`
    over its lines, summed after each line is individually rounded."

    Two lines each raw 200.5c round_half_up to 201c; total 402 (not 401).

    Design: Difficulty/combinatorial_formula/per_line_round_then_sum_ordering
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="SPLIT_CUT", species="LAMB", base_price_cents_per_kg=2005)
    cust = create_customer(full_name="Sam Split", phone="555-0003")
    order = get_success_data(
        api.create_custom_order(
            {"customer_id": cust["id"], "order_kind": "STANDARD",
             "lines": [
                 {"cut_type_id": cut["id"], "ordered_weight_g": 100},
                 {"cut_type_id": cut["id"], "ordered_weight_g": 100},
             ]},
            CLERK,
        )
    )
    assert order["estimated_total_cents"] == 402, (
        f"round-per-line-then-sum expects 402, got {order['estimated_total_cents']}"
    )


def test_per_line_round_half_up_single_line(api):
    """PRD §2.6: "**Round half up** is used for monetary results: the value is
    rounded to the nearest whole cent, and a value exactly halfway between two
    cents rounds up to the larger cent."

    One line 100g at 2005c/kg: raw 200.5c -> round_half_up -> 201c.

    Design: Difficulty/combinatorial_formula/per_line_round_then_sum_ordering
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="SPLIT_CUT", species="LAMB", base_price_cents_per_kg=2005)
    cust = create_customer(full_name="Sandy Single", phone="555-0033")
    order = get_success_data(
        api.create_custom_order(
            {"customer_id": cust["id"], "order_kind": "STANDARD",
             "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 100}]},
            CLERK,
        )
    )
    assert order["estimated_total_cents"] == 201, (
        f"raw 200.5c rounds half up to 201, got {order['estimated_total_cents']}"
    )


# ===========================================================================
# Corner: calculations / preferred_tier_discount_applied_on_estimate
# ===========================================================================
def test_preferred_tier_discount_on_estimate(api):
    """PRD §3.4: "A tier discount fraction is selected: 0 for a `STANDARD`
    customer, the policy's `preferred_discount_pct` for a `PREFERRED` customer,
    and the policy's `wholesale_discount_pct` for a `WHOLESALE` customer."

    PREFERRED 2000g RIBEYE: 2000*4.0*0.9 = 7200c.

    Design: Corner/calculations/preferred_tier_discount_applied_on_estimate
    """
    ensure_pricing_policy()
    cut = create_cut_type(code="RIBEYE", species="BEEF", base_price_cents_per_kg=4000)
    cust = create_customer(full_name="Petra Preferred", phone="555-1004",
                           loyalty_tier="PREFERRED")
    order = get_success_data(
        api.create_custom_order(
            {"customer_id": cust["id"], "order_kind": "STANDARD",
             "lines": [{"cut_type_id": cut["id"], "ordered_weight_g": 2000}]},
            CLERK,
        )
    )
    assert order["estimated_total_cents"] == 7200, (
        f"expected 7200, got {order['estimated_total_cents']}"
    )


# ===========================================================================
# Corner: calculations / holiday_deposit_quarter_of_estimate
# ===========================================================================
def test_holiday_deposit_quarter_of_estimate(api):
    """PRD §3.6: "On holiday placement the server sets the order's `deposit_cents`
    to one quarter of the order's `estimated_total_cents`, rounded half up once on
    the order-level total (not per line)."

    Estimate 8000c -> deposit 2000c.

    Design: Corner/calculations/holiday_deposit_quarter_of_estimate
    """
    setup = setup_holiday_window_before_cutoff(capacity_g=100000)
    cut = setup["cut_type"]
    window = setup["window"]
    cust = create_customer(full_name="Holly Deposit", phone="555-1005")
    order = place_holiday_order(cust["id"], window["id"], [(cut["id"], 2000)])
    assert order["estimated_total_cents"] == 8000
    assert order["deposit_cents"] == 2000, f"expected deposit 2000, got {order['deposit_cents']}"
