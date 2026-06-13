"""Calculation depth: dual-variant roast yield, dual-variant account balance, pinned
order-pricing rounding, and the tier-discount calculation.

Covers queue A (difficulty) instances dual_roast_yield_planned_vs_actual_diverges,
dual_account_balance_posted_vs_projected_diverges,
pricing_round_per_line_then_sum_order_pinned, plus queue B order_discount_applied_on_tier.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_catalog, produce_roasted_lot, create_green_lot, create_planned_batch,
    setup_shipped_order, issue_invoice,
    start_roast_batch_payload, complete_roast_batch_payload,
    create_order_payload, order_line,
    api_client, TEST_USERS,
)

ROASTER = TEST_USERS["roaster_headers"]
SALES = TEST_USERS["sales_headers"]


# ─── dual_variant_calc / dual_roast_yield_planned_vs_actual_diverges ────────

def test_planned_roasted_kg_forward_estimate(api):
    """PRD §3.3: "its `planned_roasted_kg` is `planned_green_kg` multiplied by one minus
    the profile's `expected_shrink_bps` divided by ten thousand, rounded half-up to three
    decimals."

    Design: Difficulty/dual_variant_calc/dual_roast_yield_planned_vs_actual_diverges
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "Filter City", "roast_level": "MEDIUM",
         "expected_shrink_bps": 1500, "charge_temp_c": 200}, ROASTER))
    product = get_success_data(api.create_product(
        {"sku": "SKU-FC", "name": "Filter City Blend", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 1850, "freshness_window_days": 14}, ROASTER))
    gl = get_success_data(api.create_green_lot(
        {"origin": "Ethiopia Yirgacheffe", "lot_ref": "ETH-001",
         "received_kg": 50, "par_level_kg": 10}, ROASTER))
    batch = validate_success(api.create_roast_batch(
        {"green_lot_id": gl["id"], "product_id": product["id"],
         "planned_green_kg": 20, "expected_green_lot_version": gl["version"]}, ROASTER), 201)
    # planned_green_kg 20 * (1 - 1500/10000) = 20 * 0.85 = 17.000
    assert batch["planned_roasted_kg"] == 17.000, \
        f"expected planned_roasted_kg 17.000, got {batch['planned_roasted_kg']}"


def test_actual_roast_yield_diverges_from_planned(api):
    """PRD §3.3: "computes the batch's `actual_shrink_bps` as one minus the ratio of
    `actual_roasted_kg` to `actual_green_kg`, multiplied by ten thousand, rounded half-up
    to a whole number".

    Design: Difficulty/dual_variant_calc/dual_roast_yield_planned_vs_actual_diverges
    """
    profile = get_success_data(api.create_roast_profile(
        {"name": "Filter City", "roast_level": "MEDIUM",
         "expected_shrink_bps": 1500, "charge_temp_c": 200}, ROASTER))
    product = get_success_data(api.create_product(
        {"sku": "SKU-FC", "name": "Filter City Blend", "roast_profile_id": profile["id"],
         "base_price_cents_per_kg": 1850, "freshness_window_days": 14}, ROASTER))
    gl = get_success_data(api.create_green_lot(
        {"origin": "Ethiopia Yirgacheffe", "lot_ref": "ETH-001",
         "received_kg": 50, "par_level_kg": 10}, ROASTER))
    batch = get_success_data(api.create_roast_batch(
        {"green_lot_id": gl["id"], "product_id": product["id"],
         "planned_green_kg": 20, "expected_green_lot_version": gl["version"]}, ROASTER))
    planned = batch["planned_roasted_kg"]
    api.start_roast_batch(batch["id"], start_roast_batch_payload(18.0), ROASTER)
    api.drop_roast_batch(batch["id"], ROASTER)
    done = validate_success(api.complete_roast_batch(
        batch["id"], complete_roast_batch_payload(15.3), ROASTER), 200)
    # actual_shrink_bps = round_half_up((1 - 15.3/18.0) * 10000) = round(1500.0) = 1500
    assert done["actual_roasted_kg"] == 15.300, \
        f"expected actual_roasted_kg 15.300, got {done['actual_roasted_kg']}"
    assert done["actual_shrink_bps"] == 1500, \
        f"expected actual_shrink_bps 1500, got {done['actual_shrink_bps']}"
    assert planned == 17.000
    assert planned != done["actual_roasted_kg"], \
        "planned (forward estimate) must diverge from measured actual roasted weight"


# ─── dual_variant_calc / dual_account_balance_posted_vs_projected_diverges ──

def test_posted_balance_excludes_unbilled_candidate(api):
    """PRD §2.9: "a running `outstanding_balance_cents`, which is the sum of
    `amount_due_cents` over the account's invoices whose status is `ISSUED`,
    `PARTIALLY_PAID`, or `OVERDUE`; fully `PAID` invoices are excluded."

    Design: Difficulty/dual_variant_calc/dual_account_balance_posted_vs_projected_diverges
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 200000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 30},
    )
    acct = cat["account"]
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=120, actual_roasted_kg=100)
    # First order: 75 kg @ 2000 = 150000 -> fulfill, ship, invoice (posted 150000).
    order1, _ = setup_shipped_order(acct["id"], prod["id"], lot["id"], qty_kg=75, allocated_kg=75)
    issue_invoice(order1["id"])
    # Second order: 30 kg @ 2000 = 60000, fulfilled but NOT yet invoiced.
    order2, _ = setup_shipped_order(acct["id"], prod["id"], lot["id"], qty_kg=30, allocated_kg=25)

    acct_read = validate_success(api.get_account(acct["id"], SALES), 200)
    # Posted balance reflects only the issued invoice, not the un-invoiced candidate order.
    assert acct_read["outstanding_balance_cents"] == 150000, \
        f"posted balance should be 150000, got {acct_read['outstanding_balance_cents']}"
    assert order2["total_cents"] == 60000


def test_projected_balance_blocks_invoice_beyond_posted_view(api):
    """PRD §3.6: "the account's current posted `outstanding_balance_cents` plus this order's
    `total_cents` must not exceed the account's `credit_limit_cents`. This is the projected
    balance — the posted balance plus the candidate order's total, computed before the invoice
    exists, so a credit decision can differ from the posted view for otherwise-identical
    invoice data."

    Design: Difficulty/dual_variant_calc/dual_account_balance_posted_vs_projected_diverges
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 60},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 200000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 30},
    )
    acct = cat["account"]
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=120, actual_roasted_kg=100)
    order1, _ = setup_shipped_order(acct["id"], prod["id"], lot["id"], qty_kg=75, allocated_kg=75)
    issue_invoice(order1["id"])
    order2, _ = setup_shipped_order(acct["id"], prod["id"], lot["id"], qty_kg=30, allocated_kg=25)
    # Posted 150000 + candidate 60000 = projected 210000 > limit 200000 -> rejected.
    from test_helpers import validate_error
    res = api.invoice_order(order2["id"], SALES)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")
    order2_read = validate_success(api.get_order(order2["id"], SALES), 200)
    assert order2_read["billing_status"] == "UNBILLED"


# ─── combinatorial_formula / pricing_round_per_line_then_sum_order_pinned ───

def test_order_pricing_round_per_line_then_sum(api):
    """PRD §3.4: "each line's contribution is `qty_kg` multiplied by that product's
    `base_price_cents_per_kg`, rounded half-up to whole cents per line. The order's
    `subtotal_cents` is the sum of these already-rounded per-line amounts — the per-line
    rounding happens first, then the summation, never the other way around."

    Design: Difficulty/combinatorial_formula/pricing_round_per_line_then_sum_order_pinned
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 1200, "freshness_max_days": 30, "min_monthly_kg": 100},
        account_overrides={"net_terms_days": 15, "credit_limit_cents": 500000},
        product_overrides={"base_price_cents_per_kg": 333, "freshness_window_days": 21},
    )
    prod = cat["product"]
    order = validate_success(api.create_order(
        cat["account"]["id"],
        create_order_payload([order_line(prod["id"], 1.5), order_line(prod["id"], 2.5)]),
        SALES), 201)
    # round(1.5*333)=round(499.5)=500; round(2.5*333)=round(832.5)=833; subtotal=1333.
    assert order["subtotal_cents"] == 1333, \
        f"round-per-line-then-sum subtotal must be 1333, got {order['subtotal_cents']}"


def test_order_discount_on_summed_subtotal_pinned(api):
    """PRD §3.4: "The order's `discount_cents` is the `subtotal_cents` multiplied by the
    tier's `discount_bps` divided by ten thousand, rounded half-up to whole cents, applied
    once to the whole-order subtotal rather than line by line. The order's `total_cents` is
    `subtotal_cents` minus `discount_cents`."

    Design: Difficulty/combinatorial_formula/pricing_round_per_line_then_sum_order_pinned
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 1200, "freshness_max_days": 30, "min_monthly_kg": 100},
        account_overrides={"net_terms_days": 15, "credit_limit_cents": 500000},
        product_overrides={"base_price_cents_per_kg": 333, "freshness_window_days": 21},
    )
    prod = cat["product"]
    order = validate_success(api.create_order(
        cat["account"]["id"],
        create_order_payload([order_line(prod["id"], 1.5), order_line(prod["id"], 2.5)]),
        SALES), 201)
    # discount = round_half_up(1333 * 1200 / 10000) = round(159.96) = 160; total = 1333-160 = 1173.
    assert order["discount_cents"] == 160, \
        f"expected discount_cents 160, got {order['discount_cents']}"
    assert order["total_cents"] == 1173, \
        f"expected total_cents 1173, got {order['total_cents']}"


# ─── calculations / order_discount_applied_on_tier (queue B) ────────────────

def test_tier_discount_applied_to_order(api):
    """PRD §3.4: "The order's `discount_cents` is the `subtotal_cents` multiplied by the
    tier's `discount_bps` divided by ten thousand, rounded half-up to whole cents, applied
    once to the whole-order subtotal rather than line by line. The order's `total_cents` is
    `subtotal_cents` minus `discount_cents`."

    Design: Corner/calculations/order_discount_applied_on_tier
    """
    cat = setup_catalog(
        tier_overrides={"discount_bps": 500, "freshness_max_days": 60, "min_monthly_kg": 0},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2000, "freshness_window_days": 60},
    )
    prod = cat["product"]
    order = validate_success(api.create_order(
        cat["account"]["id"],
        create_order_payload([order_line(prod["id"], 10)]), SALES), 201)
    # subtotal = round(10*2000)=20000; discount = round(20000*500/10000)=1000; total=19000.
    assert order["subtotal_cents"] == 20000
    assert order["discount_cents"] == 1000
    assert order["total_cents"] == 19000
