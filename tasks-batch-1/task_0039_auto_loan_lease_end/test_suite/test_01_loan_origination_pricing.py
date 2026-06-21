"""Loan origination pricing: tier-selected APR, amortized monthly payment,
initial state and computed-field freezing.
"""
from test_helpers import (
    validate_success,
    create_active_rate_card, create_customer, create_vehicle,
    create_loan_payload,
    TEST_USERS, make_borrower_headers,
    assert_loan, assert_customer,
)

FM = TEST_USERS["finance_manager_headers"]


def test_loan_initial_state_current_with_frozen_fields(api):
    """PRD §3.2: "At origination the loan's `principal_balance_cents` is initialized to its
    `financed_principal_cents`, its `payments_made_count` starts at 0, its `missed_payment_count`
    starts at 0, and its `status` is `CURRENT`."
    PRD §3.2: "The `financed_principal_cents` is the vehicle's `sale_price_cents` minus the loan's
    `down_payment_cents`."

    Design: Corner/state_machines/loan_initial_state_current
    """
    create_active_rate_card()
    customer = create_customer(fico_score=760)
    vehicle = create_vehicle(sale_price_cents=3_000_000)
    res = api.create_loan(create_loan_payload(customer["id"], vehicle["id"],
                          down_payment_cents=500_000, term_months=60), FM)
    loan = validate_success(res, 201)
    assert_loan(loan)
    assert loan["status"] == "CURRENT"
    assert loan["principal_balance_cents"] == 2_500_000
    assert loan["monthly_payment_cents"] == 46030
    assert loan["apr"] == 0.0399


def test_loan_initial_payments_made_count_zero(api):
    """PRD §3.2: "At origination the loan's `principal_balance_cents` is initialized to its
    `financed_principal_cents`, its `payments_made_count` starts at 0, its `missed_payment_count`
    starts at 0, and its `status` is `CURRENT`."

    Design: Corner/state_machines/loan_initial_state_current
    """
    create_active_rate_card()
    customer = create_customer(fico_score=760)
    vehicle = create_vehicle(sale_price_cents=3_000_000)
    loan = validate_success(api.create_loan(
        create_loan_payload(customer["id"], vehicle["id"],
                            down_payment_cents=500_000, term_months=60), FM), 201)
    assert loan["payments_made_count"] == 0
    assert loan["missed_payment_count"] == 0
    assert loan["financed_principal_cents"] == 2_500_000


def test_loan_tier3_apr_and_monthly_payment(api):
    """PRD §3.2: "The loan's `apr` is selected from the pinned rate card according to the
    customer's `fico_tier` at origination — `tier_1_apr` for `TIER_1`, `tier_2_apr` for `TIER_2`,
    `tier_3_apr` for `TIER_3`, and `tier_4_apr` for `TIER_4`."

    Design: Corner/calculations/loan_monthly_tier3_apr_selected
    """
    create_active_rate_card()
    customer = create_customer(fico_score=650)  # TIER_3 (>=620, <680)
    vehicle = create_vehicle(sale_price_cents=3_000_000)
    loan = validate_success(api.create_loan(
        create_loan_payload(customer["id"], vehicle["id"],
                            down_payment_cents=300_000, term_months=60), FM), 201)
    assert loan["apr"] == 0.0899
    assert loan["monthly_payment_cents"] == 56034
    assert loan["financed_principal_cents"] == 2_700_000


def test_customer_fico_tier_computed_tier1(api):
    """PRD §3.1: "If the score is greater than or equal to the active card's `tier_1_min_fico`,
    the tier is `TIER_1`."

    Design: Corner/entities/create_customer_returns_201_with_computed_tier
    """
    create_active_rate_card()
    res = api.create_customer({"full_name": "Test One", "email": "t1@x.com", "fico_score": 760}, FM)
    customer = validate_success(res, 201)
    assert_customer(customer)
    assert customer["fico_tier"] == "TIER_1"
    assert customer["version"] == 1


def test_customer_fico_tier_tier4_below_lowest_breakpoint(api):
    """PRD §3.1: "A score below `tier_3_min_fico` falls into `TIER_4`."

    Design: Corner/entities/fico_tier_tier4_below_lowest_breakpoint
    """
    create_active_rate_card()
    customer = validate_success(api.create_customer(
        {"full_name": "Low Score", "email": "low@x.com", "fico_score": 600}, FM), 201)
    assert customer["fico_tier"] == "TIER_4"


def test_origination_records_loan_fields_in_same_response(api):
    """PRD §3.2: "As the closing side effect, the associated vehicle's `status` is set to
    `FINANCED`."
    PRD §3.2: "The `monthly_payment_cents` is the standard amortized level payment: letting the
    financed principal be the present value, the monthly rate be the loan's `apr` divided by 12,
    and the number of periods be `term_months`, the payment equals the present value multiplied
    by the quantity (monthly rate times (one plus the monthly rate) raised to the number of
    periods), divided by ((one plus the monthly rate) raised to the number of periods, minus
    one)."

    Design: Corner/consistency_model/origination_changes_visible_same_request
    """
    create_active_rate_card()
    customer = create_customer(fico_score=760)
    vehicle = create_vehicle(sale_price_cents=3_000_000)
    loan = validate_success(api.create_loan(
        create_loan_payload(customer["id"], vehicle["id"],
                            down_payment_cents=500_000, term_months=60), FM), 201)
    # monthly_payment_cents already computed in the same POST response.
    assert loan["monthly_payment_cents"] == 46030
    # And the financed vehicle reflects FINANCED on the immediate follow-up GET.
    vehicle_after = validate_success(api.get_vehicle(vehicle["id"], FM), 200)
    assert vehicle_after["status"] == "FINANCED"
