"""Lease origination pricing: the pinned evaluation order for base monthly and
tax (both rounded from the same unrounded pre-tax sum).
"""
from test_helpers import (
    validate_success,
    create_active_rate_card, create_customer, create_vehicle,
    create_lease_payload,
    TEST_USERS,
    assert_lease,
)

FM = TEST_USERS["finance_manager_headers"]


def test_lease_base_monthly_rounded_from_unrounded_sum(api):
    """PRD §3.5: "The pre-tax monthly figure `base_monthly_cents` is the sum of the depreciation
    fee and the finance fee, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/lease_monthly_evaluation_order_pinned
    """
    create_active_rate_card()
    customer = create_customer(fico_score=760)
    vehicle = create_vehicle(sale_price_cents=3_200_000, residual_value_cents=1_850_000)
    lease = validate_success(api.create_lease(
        create_lease_payload(customer["id"], vehicle["id"],
                            down_payment_cents=0, term_months=36), FM), 201)
    assert_lease(lease)
    assert lease["base_monthly_cents"] == 43813


def test_lease_monthly_payment_taxes_unrounded_sum(api):
    """PRD §3.5: "The monthly tax is that same unrounded sum of the depreciation fee and finance
    fee, multiplied by the rate card's `lease_tax_rate`, rounded half-up to whole cents. The
    lease's `monthly_payment_cents` is then `base_monthly_cents` plus that rounded tax."

    Design: Difficulty/combinatorial_formula/lease_monthly_evaluation_order_pinned
    """
    create_active_rate_card()
    customer = create_customer(fico_score=760)
    vehicle = create_vehicle(sale_price_cents=3_200_000, residual_value_cents=1_850_000)
    lease = validate_success(api.create_lease(
        create_lease_payload(customer["id"], vehicle["id"],
                            down_payment_cents=0, term_months=36), FM), 201)
    # base 43813 + tax 3176 = 46989. Taxing the pre-rounded base would diverge.
    assert lease["monthly_payment_cents"] == 46989
