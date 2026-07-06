"""Loyalty punch accrual, reward auto-conversion, and exact compensation on void."""
import pytest

from test_helpers import (
    api_client as _ac,
    validate_success,
    TEST_USERS,
    line_item,
    setup_loyalty_at_nine_punches,
    create_cart,
)

CASHIER = TEST_USERS["cashier_headers"]


# =====================================================================
# Difficulty/transitive_cascade/retail_pay_punch_then_reward_conversion_depth3 (2)
# =====================================================================
def test_pay_crosses_punch_threshold_resets_count(api):
    """PRD §3.5: "On payment, the account earns one punch per full dozen across the
    order ... Whenever punch_count reaches the reward threshold of 10 punches, it
    auto-converts: 10 punches are removed from punch_count and 1200 cents are added
    to reward_balance_cents."

    Design: Difficulty/transitive_cascade/retail_pay_punch_then_reward_conversion_depth3
    """
    day, product, _batch, loyalty = setup_loyalty_at_nine_punches(par_qty=120)
    order = create_cart(day["id"], [line_item(product["id"], 12)],
                        loyalty_account_id=loyalty["id"])
    validate_success(_ac.pay_retail_order(day["id"], order["id"], CASHIER))
    acct = validate_success(_ac.get_loyalty_account(loyalty["id"], CASHIER))
    assert acct["punch_count"] == 0, (
        f"9 + 1 = 10 -> auto-convert resets to 0; got {acct['punch_count']}")


def test_pay_threshold_crossing_banks_reward_value(api):
    """PRD §3.5: "Whenever punch_count reaches the reward threshold of 10 punches, it
    auto-converts: 10 punches are removed from punch_count and 1200 cents are added to
    reward_balance_cents."

    Design: Difficulty/transitive_cascade/retail_pay_punch_then_reward_conversion_depth3
    """
    day, product, _batch, loyalty = setup_loyalty_at_nine_punches(par_qty=120)
    order = create_cart(day["id"], [line_item(product["id"], 12)],
                        loyalty_account_id=loyalty["id"])
    validate_success(_ac.pay_retail_order(day["id"], order["id"], CASHIER))
    acct = validate_success(_ac.get_loyalty_account(loyalty["id"], CASHIER))
    assert acct["reward_balance_cents"] == 1200, (
        f"one conversion banks 1200; got {acct['reward_balance_cents']}")


# =====================================================================
# Difficulty/compensating_invariant/void_restores_loyalty_punch_equivalents (2)
# =====================================================================
def test_void_reverses_reward_conversion_restores_punch_count(api):
    """PRD §3.5: "Both reversals restore each line product's batch sold_qty and
    remaining_qty (and restore markdown_sold_qty for marked-down lines), reverse the
    loyalty punches this order accrued, and undo any reward conversion this order
    caused (subtracting 1200 cents per conversion that this order triggered)."

    Design: Difficulty/compensating_invariant/void_restores_loyalty_punch_equivalents
    """
    day, product, _batch, loyalty = setup_loyalty_at_nine_punches(par_qty=120)
    order = create_cart(day["id"], [line_item(product["id"], 12)],
                        loyalty_account_id=loyalty["id"])
    paid = validate_success(_ac.pay_retail_order(day["id"], order["id"], CASHIER))
    voided = validate_success(_ac.void_retail_order(day["id"], order["id"], CASHIER))
    assert voided["status"] == "VOIDED"
    acct = validate_success(_ac.get_loyalty_account(loyalty["id"], CASHIER))
    assert acct["punch_count"] == 9, (
        f"void undoes the 1-dozen punch and the conversion -> back to 9; "
        f"got {acct['punch_count']}")


def test_void_drains_banked_reward_back_to_zero(api):
    """PRD §3.5: "The intended invariant is that punches earned and then reversed leave
    the account's punch count plus banked reward value exactly where it stood before
    the sale."

    Design: Difficulty/compensating_invariant/void_restores_loyalty_punch_equivalents
    """
    day, product, _batch, loyalty = setup_loyalty_at_nine_punches(par_qty=120)
    order = create_cart(day["id"], [line_item(product["id"], 12)],
                        loyalty_account_id=loyalty["id"])
    validate_success(_ac.pay_retail_order(day["id"], order["id"], CASHIER))
    validate_success(_ac.void_retail_order(day["id"], order["id"], CASHIER))
    acct = validate_success(_ac.get_loyalty_account(loyalty["id"], CASHIER))
    assert acct["reward_balance_cents"] == 0, (
        f"the order's conversion is undone -> reward balance 0; "
        f"got {acct['reward_balance_cents']}")
