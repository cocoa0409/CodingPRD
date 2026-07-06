"""Financing plans: deferred-vs-amortized cost divergence, the pinned
round-per-installment order, the accept precondition, and the principal bounds.
"""
from test_helpers import (
    ApiErrorId,
    create_financing_plan,
    create_financing_plan_payload,
    setup_presented_quote,
    validate_error,
    validate_success,
)


def test_financing_deferred_interest_total_equals_principal(api):
    """PRD §3.6: "For a `DEFERRED_INTEREST` plan, the `monthly_payment_cents` is
    the principal divided by `term_months`, rounded half up to whole cents, and
    the `total_cost_cents` equals the principal exactly — the plan is same-as-cash
    if the balance is cleared within the `promo_window_days`, so no interest is
    added."

    Design: Difficulty/dual_variant_calc/financing_deferred_vs_amortized_cost
    """
    scenario = setup_presented_quote(estimated_linear_feet=200, measured_linear_feet=200)
    plan = create_financing_plan(
        scenario["quote"]["id"], "DEFERRED_INTEREST", 0, 12, promo_window_days=365
    )
    assert plan["principal_cents"] == 570000
    assert plan["monthly_payment_cents"] == 47500
    assert plan["total_cost_cents"] == 570000


def test_financing_amortized_total_exceeds_deferred_for_same_principal(api):
    """PRD §3.6: "The `monthly_payment_cents` is that exact monthly payment
    rounded half up to whole cents, and the `total_cost_cents` is that rounded
    monthly payment multiplied by `term_months`. For the same principal, an
    amortized plan's total cost exceeds the deferred-interest total by the
    financed interest."

    Design: Difficulty/dual_variant_calc/financing_deferred_vs_amortized_cost
    """
    scenario = setup_presented_quote(estimated_linear_feet=200, measured_linear_feet=200)
    qid = scenario["quote"]["id"]
    deferred = create_financing_plan(qid, "DEFERRED_INTEREST", 0, 12, promo_window_days=365)
    amortized = create_financing_plan(qid, "AMORTIZED", 1200, 12)
    assert amortized["monthly_payment_cents"] == 50644
    assert amortized["total_cost_cents"] == 607728
    assert amortized["total_cost_cents"] > deferred["total_cost_cents"]


def test_financing_amortized_monthly_rounds_before_summation(api):
    """PRD §3.6: "The `monthly_payment_cents` is that exact monthly payment
    rounded half up to whole cents, and the `total_cost_cents` is that rounded
    monthly payment multiplied by `term_months`."

    Design: Difficulty/combinatorial_formula/financing_amortized_rounding_order_mode_b
    """
    scenario = setup_presented_quote(estimated_linear_feet=200, measured_linear_feet=200)
    plan = create_financing_plan(scenario["quote"]["id"], "AMORTIZED", 1200, 12)
    assert plan["monthly_payment_cents"] == 50644


def test_financing_amortized_total_is_rounded_monthly_times_term(api):
    """PRD §2.5: "the per-installment payment is rounded to whole cents first, and
    the total cost of financing is that rounded payment multiplied by the number
    of installments — never the exact total computed once and rounded at the end."

    Design: Difficulty/combinatorial_formula/financing_amortized_rounding_order_mode_b
    """
    scenario = setup_presented_quote(estimated_linear_feet=200, measured_linear_feet=200)
    plan = create_financing_plan(scenario["quote"]["id"], "AMORTIZED", 1200, 12)
    assert plan["total_cost_cents"] == 607728
    assert plan["total_cost_cents"] == plan["monthly_payment_cents"] * 12
    # The sum-then-round order (607726) is explicitly rejected by the PRD.
    assert plan["total_cost_cents"] != 607726


def test_financing_accept_requires_accepted_quote(api, admin_headers):
    """PRD §3.6: "Accepting a plan is permitted only when its backing quote
    (identified by the plan's `quote_id`) is itself in `ACCEPTED`; otherwise the
    acceptance is rejected with `ERR_QUOTE_NOT_ACCEPTED`."

    Design: Corner/state_machines/financing_accept_requires_quote_accepted
    """
    scenario = setup_presented_quote(estimated_linear_feet=200, measured_linear_feet=200)
    plan = create_financing_plan(
        scenario["quote"]["id"], "DEFERRED_INTEREST", 0, 12, promo_window_days=365
    )
    resp = api.transition_financing_plan(plan["id"], {"to_status": "ACCEPTED"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_ACCEPTED)


def test_financing_below_minimum_principal_returns_error(api, admin_headers):
    """PRD §3.6: "The financed principal must fall within the program's bounds: it
    must be at least 100,000 cents ($1,000), else `ERR_FINANCE_BELOW_MIN`, and it
    must not exceed 5,000,000 cents ($50,000), else `ERR_FINANCE_LIMIT_EXCEEDED`."

    Design: Corner/validations/finance_below_min_returns_error
    """
    scenario = setup_presented_quote(estimated_linear_feet=30, measured_linear_feet=30)
    assert scenario["quote"]["total_cents"] == 90000  # below the 100000 minimum
    resp = api.create_financing_plan(
        create_financing_plan_payload(scenario["quote"]["id"], "AMORTIZED", 1200, 12),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FINANCE_BELOW_MIN)


def test_financing_above_maximum_principal_returns_error(api, admin_headers):
    """PRD §3.6: "The financed principal must fall within the program's bounds: it
    must be at least 100,000 cents ($1,000), else `ERR_FINANCE_BELOW_MIN`, and it
    must not exceed 5,000,000 cents ($50,000), else `ERR_FINANCE_LIMIT_EXCEEDED`."

    Design: Corner/validations/finance_above_max_returns_limit_exceeded
    """
    scenario = setup_presented_quote(estimated_linear_feet=2000, measured_linear_feet=2000)
    assert scenario["quote"]["total_cents"] == 5400000  # above the 5000000 ceiling
    resp = api.create_financing_plan(
        create_financing_plan_payload(scenario["quote"]["id"], "AMORTIZED", 1200, 12),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FINANCE_LIMIT_EXCEEDED)
