"""Breadth tests over individual calculation rules: repair-invoice minimum bench
floor, trade-in condition tiers, layaway paid/remaining aggregation, and
special-order deposit ceiling rounding.
"""
import pytest

from test_helpers import (
    validate_success,
    make_customer_headers,
    create_customer,
    setup_offered_trade_in, setup_open_layaway,
    TEST_USERS,
)
import test_helpers.factories as f

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


# ===========================================================================
# Corner / calculations
# ===========================================================================
def test_repair_invoice_min_bench_floor_applies(api):
    """PRD §3.6: "It then floors that labor at a minimum bench charge of 4,000 cents
    (forty dollars): the labor used in the rest of the computation is the greater of
    the rounded labor and 4,000 cents, regardless of how few hours were entered."

    Design: Corner/calculations/repair_invoice_min_bench_floor_applies
    """
    customer = create_customer()
    ticket = validate_success(
        api.create_ticket(
            f.create_ticket_payload(customer["id"], labor_hours=0.5, labor_rate_cents=5000),
            SA,
        ),
        201,
    )
    # labor 0.5*5000 = 2500 -> floored to 4000; no parts, no rush -> 4000
    assert ticket["quoted_total_cents"] == 4000


def test_tradein_offer_new_condition_tier(api):
    """PRD §3.7: "the fraction is 0.60 for `NEW`, 0.50 for `USED`, and 0.70 for
    `VINTAGE`, so the offer is the appraised value multiplied by the condition's
    fraction, floored."

    Design: Corner/calculations/tradein_offer_new_condition_tier
    """
    customer, trade_in = setup_offered_trade_in(condition="NEW", appraised_value_cents=100000)
    # floor(100000 * 0.60) = 60000
    assert trade_in["offer_cents"] == 60000


def test_layaway_paid_remaining_aggregation(api):
    """PRD §3.5: "The paid figure is the initial deposit plus the sum of all
    installment amounts recorded against the plan — deposit_cents plus the total of
    every LayawayPayment.amount_cents on the plan. The remaining figure is the total
    price minus the paid figure, floored at 0"

    Design: Corner/calculations/layaway_paid_remaining_aggregation
    """
    customer, plan, unit = setup_open_layaway(
        list_price_cents=60000, deposit_cents=20000, installments=[20000, 20000]
    )
    data = validate_success(api.get_layaway(plan["id"], make_customer_headers(customer["id"])), 200)
    assert data["paid_cents"] == 60000
    assert data["remaining_cents"] == 0


def test_special_order_deposit_ceil_rounding(api):
    """PRD §3.8: "On creation the system computes required_deposit_cents as the quoted
    price multiplied by the deposit fraction, rounded up to the next whole cent (a
    ceiling)."

    Design: Corner/calculations/special_order_deposit_ceil_rounding
    """
    customer = create_customer()
    order = validate_success(
        api.create_special_order(
            f.create_special_order_payload(customer["id"], quoted_price_cents=99999, deposit_pct=0.25),
            SA,
        ),
        201,
    )
    # ceil(99999 * 0.25) = ceil(24999.75) = 25000
    assert order["required_deposit_cents"] == 25000
