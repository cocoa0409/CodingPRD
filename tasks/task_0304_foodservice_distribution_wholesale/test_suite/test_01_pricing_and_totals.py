"""Line pricing (ordered-basis tier, allocated-basis charge) and order totals.

Covers difficulty queue rules dual_variant_calc (pricing instance), combinatorial_formula,
plus the corner consistency_model instance for immediate totals visibility.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_catalog, create_submitted_order, get_customer_version, approve_credit_payload,
    TEST_USERS,
)

CREDIT = TEST_USERS["credit_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def test_line_prices_tier_on_ordered_but_charges_allocated(api):
    """PRD §3.4: "The pricing tier is chosen on the quantity the customer *ordered*,
    while the charge is computed on the quantity actually *allocated* — the same line
    priced on two different quantity bases."
    PRD §3.4: "The line's `extended_price_cents` is the number of full cases times
    `unit_case_price_cents` plus the residual split count times that rounded-up
    per-split price."

    A CASE-5 order (60 ordered splits -> tier2 @ 2200) shorts to 48 allocated splits
    (4 cases): tier still 2200, but charge = 4 * 2200 = 8800, not 5 * 2200.

    Design: Difficulty/dual_variant_calc/line_pricing_ordered_tier_vs_allocated_charge
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True,
                        tiers=((1, 2400), (5, 2200), (10, 2000)),
                        on_hand_splits=48, credit_limit_cents=100000, split_fee_cents=0)
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 5)])
    line = lines[0]

    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    line_after = validate_success(api.get_order_line(line["id"], SALES), 200)
    assert line_after["unit_case_price_cents"] == 2200
    assert line_after["allocated_splits"] == 48
    assert line_after["short_splits"] == 12
    assert line_after["extended_price_cents"] == 8800
    assert approved["order_total_cents"] == 8800


def test_split_line_tier_selection_with_split_residual(api):
    """PRD §3.4: "if that comes out below 1 — as it does for a sub-case SPLIT-only line —
    it is treated as 1 so the line still prices at the lowest tier."
    PRD §3.4: "Each residual split is priced at the case price divided by `splits_per_case`,
    rounded up to the next whole cent (rounding in the distributor's favor)."

    A SPLIT-14 line (splits_per_case 12 @ tier 2400): 1 full case (2400) + 2 residual
    splits at ceil(2400/12)=200 -> 2400 + 400 = 2800.

    Design: Difficulty/combinatorial_formula/line_pricing_tier_select_with_split_residual_mode_a
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True, tiers=((1, 2400),),
                        on_hand_splits=14, credit_limit_cents=100000, split_fee_cents=0)
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "SPLIT", 14)])
    line = lines[0]

    cust_v = get_customer_version(cat["customer"]["id"])
    validate_success(api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    line_after = validate_success(api.get_order_line(line["id"], SALES), 200)
    assert line_after["unit_case_price_cents"] == 2400
    assert line_after["extended_price_cents"] == 2800


def test_order_totals_round_per_line_then_sum_with_split_fee(api):
    """PRD §3.4: "The order's `goods_subtotal_cents` is the sum of `extended_price_cents`
    across all lines whose `line_status` is not `REMOVED`."
    PRD §3.4: "The order's `split_fee_total_cents` is the customer's `split_fee_cents`
    multiplied by the number of lines that are in SPLIT units, are not removed, and
    allocated more than zero splits — the per-split handling fee is charged once for
    each such qualifying SPLIT line."
    PRD §3.4: "Each line is rounded by its own pricing before these sums are taken;
    the order computes line-first then aggregates."

    Line1 CASE 5 @ tier2 = 11000; Line2 SPLIT 14 = 2800; one split_fee of 50.
    goods_subtotal 13800, split_fee_total 50, order_total 13850.

    Design: Difficulty/combinatorial_formula/order_totals_round_per_line_then_sum_mode_b
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True,
                        tiers=((1, 2400), (5, 2200), (10, 2000)),
                        on_hand_splits=74, credit_limit_cents=100000, split_fee_cents=50)
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 5), (cat["product"]["id"], "SPLIT", 14)])
    line1, line2 = lines

    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    l1 = validate_success(api.get_order_line(line1["id"], SALES), 200)
    l2 = validate_success(api.get_order_line(line2["id"], SALES), 200)
    assert l1["extended_price_cents"] == 11000
    assert l2["extended_price_cents"] == 2800
    assert approved["goods_subtotal_cents"] == 13800
    assert approved["split_fee_total_cents"] == 50
    assert approved["order_total_cents"] == 13850


def test_extended_price_tier_on_ordered_basis_alt(api):
    """PRD §3.4: "To pick the tier, the system first finds the case-equivalents of the
    ordered quantity ... Among the fulfilled product's `PriceTier` rows whose `min_cases`
    is at most that ordered case-equivalent count, the system selects the one with the
    greatest `min_cases`."

    Second test of the dual-variant pricing rule: a fully-allocated CASE-5 line
    (60 splits in stock) selects tier2 @ 2200 and charges all 5 cases -> 11000.

    Design: Difficulty/dual_variant_calc/line_pricing_ordered_tier_vs_allocated_charge
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True,
                        tiers=((1, 2400), (5, 2200), (10, 2000)),
                        on_hand_splits=60, credit_limit_cents=100000, split_fee_cents=0)
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 5)])
    line = lines[0]

    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    line_after = validate_success(api.get_order_line(line["id"], SALES), 200)
    assert line_after["unit_case_price_cents"] == 2200
    assert line_after["allocated_splits"] == 60
    assert line_after["extended_price_cents"] == 11000
    assert approved["order_total_cents"] == 11000


def test_combinatorial_tiers_three_tier_table_alt(api):
    """PRD §3.4: "A given tier's `case_price_cents` applies when the ordered
    case-equivalent count is at least that tier's `min_cases` and below the next higher
    tier's `min_cases`."

    Second test of the combinatorial-formula rule, exercising the >=3-input interaction
    (ordered_qty, splits_per_case, three-tier table) with a SPLIT residual: a SPLIT-14
    line on a three-tier product prices at the lowest tier (2400) -> 2800.

    Design: Difficulty/combinatorial_formula/line_pricing_tier_select_with_split_residual_mode_a
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True,
                        tiers=((1, 2400), (5, 2200), (10, 2000)),
                        on_hand_splits=14, credit_limit_cents=100000, split_fee_cents=0)
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "SPLIT", 14)])
    line = lines[0]

    cust_v = get_customer_version(cat["customer"]["id"])
    validate_success(api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    line_after = validate_success(api.get_order_line(line["id"], SALES), 200)
    assert line_after["unit_case_price_cents"] == 2400
    assert line_after["extended_price_cents"] == 2800


def test_order_totals_two_split_lines_each_charge_split_fee(api):
    """PRD §3.4: "The order's `goods_subtotal_cents` is the sum of `extended_price_cents`
    across all lines whose `line_status` is not `REMOVED`."
    PRD §3.4: "The order's `split_fee_total_cents` is the customer's `split_fee_cents`
    multiplied by the number of lines that are in SPLIT units, are not removed, and
    allocated more than zero splits — the per-split handling fee is charged once for each
    such qualifying SPLIT line."
    PRD §3.4: "Each line is rounded by its own pricing before these sums are taken; the
    order computes line-first then aggregates."

    Second test of the round-per-line-then-sum rule with two qualifying SPLIT lines: two
    SPLIT-14 lines each price 2800 (goods 5600) and each draws the 50 split fee
    (split_fee_total 100) -> order_total 5700.

    Design: Difficulty/combinatorial_formula/order_totals_round_per_line_then_sum_mode_b
    """
    cat = setup_catalog(splits_per_case=12, split_allowed=True, tiers=((1, 2400),),
                        on_hand_splits=28, credit_limit_cents=100000, split_fee_cents=50)
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "SPLIT", 14), (cat["product"]["id"], "SPLIT", 14)])
    line1, line2 = lines

    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    l1 = validate_success(api.get_order_line(line1["id"], SALES), 200)
    l2 = validate_success(api.get_order_line(line2["id"], SALES), 200)
    assert l1["extended_price_cents"] == 2800
    assert l2["extended_price_cents"] == 2800
    assert approved["goods_subtotal_cents"] == 5600
    assert approved["split_fee_total_cents"] == 100
    assert approved["order_total_cents"] == 5700


def test_totals_visible_in_approve_response_immediately(api):
    """PRD §2.5: "the entire set of effects is applied together and immediately;
    the system does not defer reconciliation."
    PRD §3.4: "if the customer's `ar_balance_cents` plus this order's `order_total_cents`
    is at most the customer's `credit_limit_cents`, the order's `credit_status` becomes
    `APPROVED`."

    The approve-credit response itself carries the freshly-computed order_total_cents
    (2 cases @ 2400 = 4800) and credit_status APPROVED — no re-read needed.

    Design: Corner/consistency_model/approve_credit_totals_visible_in_same_response
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 2)])

    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)
    assert approved["order_total_cents"] == 4800
    assert approved["credit_status"] == "APPROVED"
