"""Pricing and installment-schedule generation: Pay-in-4 vs Monthly amortization,
the eligibility limit, and the finance charge.

Covers queue A (difficulty) instances dual_variant_calc and combinatorial_formula,
plus queue B corner instances on computed credit fields and monthly amortization.
"""
from test_helpers import (
    validate_success,
    setup_activated_loan,
    create_merchant,
    create_borrower,
    create_application,
    decide_application,
    get_loan,
    get_borrower,
    list_installments,
    installments_by_sequence,
    find_installment,
    assert_loan,
    assert_borrower,
    make_servicer_headers,
)

SERVICER = make_servicer_headers()


def test_pay_in_4_and_monthly_diverge_finance_charge_on_same_principal(api):
    """PRD §3.2: "The annual percentage rate, apr_bps, is 0 for a PAY_IN_4 plan and
    is the fixed constant 1990 basis points (19.90%) for a MONTHLY plan."
    PRD §3.2: "For Pay-in-4 the finance charge is exactly 0 and the total of payments
    equals the financed principal."

    Design: Difficulty/dual_variant_calc/schedule_pay_in_4_vs_monthly_diverge_on_same_principal
    """
    # Loan A: PAY_IN_4, financed 100000 -> finance_charge 0.
    ctx_a = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                 borrower_email="ba@x.com", merchant_display_name="MA")
    loan_a = get_loan(ctx_a["loan"]["id"])
    assert_loan(loan_a)
    assert loan_a["finance_charge_cents"] == 0, "PAY_IN_4 finance charge must be 0"
    assert loan_a["financed_principal_cents"] == 100_000

    # Loan B: MONTHLY term 6, financed 120000 -> finance_charge 7060.
    ctx_b = setup_activated_loan(cart_amount_cents=120_000, plan_type="MONTHLY",
                                 term_months=6, borrower_email="bb@x.com",
                                 merchant_display_name="MB")
    loan_b = get_loan(ctx_b["loan"]["id"])
    assert_loan(loan_b)
    assert loan_b["finance_charge_cents"] == 7060, (
        f"MONTHLY/6 finance charge expected 7060, got {loan_b['finance_charge_cents']}"
    )
    assert loan_b["financed_principal_cents"] == 120_000


def test_eligibility_provisional_limit_static_and_final_forces_counter(api):
    """PRD §3.1: "a score of at least 580 but below 670 yields a base limit of
    50000 cents". PRD §3.1: "The eligible credit limit is the smaller of the base
    limit and the income cap."
    PRD §3.3: "the application is countered: it moves from SUBMITTED to COUNTERED,
    and approved_down_payment_cents is raised to the minimum down payment that fits
    the limit, namely cart_amount_cents minus the available credit."

    Design: Difficulty/dual_variant_calc/eligibility_provisional_vs_final_diverge_on_borrower
    """
    merchant = create_merchant(mdr_bps=600)
    # score 620, income 2_000_000 -> base 50000, income cap 200000 -> min = 50000.
    borrower = create_borrower(email="bc@x.com", full_name="BC",
                               soft_credit_score=620, annual_income_cents=2_000_000)
    assert borrower["eligible_credit_limit_cents"] == 50_000
    assert borrower["available_credit_cents"] == 50_000

    # cart 50001 down 0 -> need 50001 > avail 50000, but cart-1=50000 <= avail -> COUNTER.
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=50_001, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    decided = decide_application(application["id"], "COUNTER")
    assert decided["status"] == "COUNTERED"
    assert decided["approved_down_payment_cents"] == 1, (
        "countered down payment = cart_amount - available = 50001 - 50000 = 1"
    )
    assert decided["financed_principal_cents"] == 50_000

    # Provisional limit is static after registration.
    refreshed = get_borrower(borrower["id"])
    assert refreshed["eligible_credit_limit_cents"] == 50_000


def test_eligibility_provisional_limit_is_min_of_base_and_income_cap(api):
    """PRD §3.1: "Separately, an income cap is computed as the floor of ten percent of
    annual_income_cents. The eligible credit limit is the smaller of the base limit and
    the income cap."

    Design: Difficulty/dual_variant_calc/eligibility_provisional_vs_final_diverge_on_borrower
    """
    # score 620 -> base 50000; income 300000 -> income cap floor(30000) = 30000 -> min 30000.
    borrower = create_borrower(email="bc2@x.com", full_name="BC2",
                               soft_credit_score=620, annual_income_cents=300_000)
    assert borrower["eligible_credit_limit_cents"] == 30_000, (
        "income cap (30000) tighter than base limit (50000)"
    )
    assert borrower["available_credit_cents"] == 30_000


def test_monthly_amortization_schedule_amounts_and_principal_sum(api):
    """PRD §3.4: "Each of installments one through N minus one has an amount_due_cents
    equal to the level payment rounded half up; the final installment's amount_due_cents
    is the total_of_payments_cents minus the sum of the first N minus one amounts, so
    the last installment absorbs the residual."
    PRD §3.4: "any leftover balance is added to the final installment's principal
    portion so that the principal portions sum exactly to the financed principal."

    Design: Difficulty/combinatorial_formula/monthly_amortization_nonlinear_three_inputs
    """
    ctx = setup_activated_loan(cart_amount_cents=120_000, plan_type="MONTHLY",
                               term_months=6)
    installments = installments_by_sequence(list_installments(ctx["loan"]["id"]))
    assert len(installments) == 6

    amounts = [i["amount_due_cents"] for i in installments]
    assert amounts == [21177, 21177, 21177, 21177, 21177, 21175], (
        f"MONTHLY/6 amortized schedule mismatch: {amounts}"
    )
    assert sum(amounts) == 127060, f"sum(amount_due) expected 127060, got {sum(amounts)}"

    principal_sum = sum(i["principal_portion_cents"] for i in installments)
    assert principal_sum == 120_000, (
        f"sum(principal_portion) must equal financed principal 120000, got {principal_sum}"
    )


def test_monthly_amortization_last_installment_absorbs_residual(api):
    """PRD §3.4: "Across both variants amounts are integer cents, each per-installment
    amount is rounded half up, and the last installment absorbs the residual so the
    amount_due_cents sum to total_of_payments_cents and the principal_portion_cents
    sum to financed_principal_cents."

    Design: Difficulty/combinatorial_formula/monthly_amortization_nonlinear_three_inputs
    """
    ctx = setup_activated_loan(cart_amount_cents=120_000, plan_type="MONTHLY",
                               term_months=6)
    loan = get_loan(ctx["loan"]["id"])
    installments = installments_by_sequence(list_installments(loan["id"]))

    total_of_payments = loan["financed_principal_cents"] + loan["finance_charge_cents"]
    assert total_of_payments == 127060
    assert sum(i["amount_due_cents"] for i in installments) == total_of_payments
    # The residual lands on installment 6 (21175, one cent below the level 21177).
    last = find_installment(installments, 6)
    assert last["amount_due_cents"] == 21175


def test_pay_in_4_schedule_even_split_with_residual_on_fourth(api):
    """PRD §3.4: "A base amount is the floor of the principal divided by four, and the
    residual is the principal minus four times the base."
    PRD §3.4: "Each of installments one through three has an amount_due_cents equal to
    the base; installment four has an amount_due_cents equal to the base plus the
    residual."

    Design: Difficulty/dual_variant_calc/schedule_pay_in_4_vs_monthly_diverge_on_same_principal
    """
    # financed 100000 -> base 25000, residual 0 -> [25000,25000,25000,25000].
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    installments = installments_by_sequence(list_installments(ctx["loan"]["id"]))
    assert len(installments) == 4
    amounts = [i["amount_due_cents"] for i in installments]
    assert amounts == [25000, 25000, 25000, 25000], f"PAY_IN_4 even split mismatch: {amounts}"
    # zero interest -> principal_portion == amount_due.
    for inst in installments:
        assert inst["principal_portion_cents"] == inst["amount_due_cents"]


def test_get_borrower_includes_computed_credit_fields(api):
    """PRD §3.1: "a score of at least 670 but below 740 yields a base limit of 200000
    cents". PRD §3.1: "with no loans yet, outstanding is zero and available equals the
    eligible limit."

    Design: Corner/entities/get_borrower_includes_computed_credit_fields
    """
    # score 700, income 3_000_000 -> base 200000, income cap 300000 -> min 200000.
    borrower = create_borrower(email="bb@x.com", full_name="BB",
                               soft_credit_score=700, annual_income_cents=3_000_000)
    resp = api.get_borrower(borrower["id"], SERVICER)
    data = validate_success(resp, 200)
    assert_borrower(data)
    assert data["eligible_credit_limit_cents"] == 200_000
    assert data["available_credit_cents"] == 200_000
    assert data["outstanding_principal_cents"] == 0
