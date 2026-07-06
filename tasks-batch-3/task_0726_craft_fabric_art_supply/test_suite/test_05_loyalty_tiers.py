"""Loyalty tier computation: forward vs chronological, silver boundary."""
from test_helpers import (
    set_clock, create_customer, create_product_with_lot,
    complete_picked_up_order, get_loyalty_account,
)


def test_forward_tier_annualizes_ytd_spend(api):
    """PRD §3.1: "divide spend_ytd_cents by that elapsed-day count and multiply by
    365 to project the full-year spend; then compare the projection to the gold
    threshold and, failing that, the silver threshold, defaulting to BASIC."

    Design: Difficulty/dual_variant_calc/loyalty_tier_forward_vs_chronological_on_account
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=30000)
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    account = get_loyalty_account(customer["id"])
    # 30000/91*365 = 120329c >= SILVER_CENTS (50000) -> SILVER.
    assert account["tier_forward"] == "SILVER"


def test_chronological_tier_sums_trailing_actual_spend(api):
    """PRD §3.1: "The tier_chronological field instead sums the final_total_cents
    of every picked-up order for the customer whose finalization falls within the
    trailing 365 days ... and compares that rolling actual spend against the same
    gold-then-silver thresholds."

    Design: Difficulty/dual_variant_calc/loyalty_tier_forward_vs_chronological_on_account
    """
    set_clock("2026-04-01T00:00:00Z")
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=10, sell_mode="UNIT", unit_price_cents=30000)
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    account = get_loyalty_account(customer["id"])
    # rolling actual spend is only 30000c < SILVER_CENTS (50000) -> BASIC.
    assert account["tier_chronological"] == "BASIC"


def test_silver_threshold_exact_boundary_chronological(api):
    """PRD §3.1: "The two silver and gold thresholds are 500 dollars and 1500
    dollars of qualifying spend respectively — that is, 50000 cents and 150000
    cents. Both tiers use an at-least comparison against these thresholds: spend
    equal to the silver threshold qualifies for SILVER"

    Design: Difficulty/boundary_precision_check/loyalty_silver_threshold_exact_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=5, sell_mode="UNIT", unit_price_cents=50000)
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    account = get_loyalty_account(customer["id"])
    # rolling spend exactly 50000 == SILVER_CENTS -> SILVER via >=.
    assert account["tier_chronological"] == "SILVER"


def test_below_silver_threshold_is_basic_chronological(api):
    """PRD §3.1: "anything below the silver threshold is BASIC."

    Design: Difficulty/boundary_precision_check/loyalty_silver_threshold_exact_boundary
    """
    set_clock("2026-06-01T00:00:00Z")
    customer = create_customer()
    product, _ = create_product_with_lot(on_hand_yards=5, sell_mode="UNIT", unit_price_cents=49999)
    complete_picked_up_order(customer["id"], product["id"], requested_yards=1)
    account = get_loyalty_account(customer["id"])
    # rolling spend 49999 < SILVER_CENTS (50000) -> BASIC.
    assert account["tier_chronological"] == "BASIC"
