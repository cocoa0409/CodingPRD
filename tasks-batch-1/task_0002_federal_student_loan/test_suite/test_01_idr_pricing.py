"""IDR / STANDARD monthly-payment pricing tests.

Covers the dual-variant calc (IBR vs SAVE divergence), the multi-input
combinatorial mode (Alaska poverty table interaction), STANDARD amortization,
PAYE point value, and the zero-discretionary floor.
"""
from test_helpers import (
    api_client, validate_success,
    setup_idr_certified_borrower_in_repayment,
    create_repayment_plan_payload,
    TEST_USERS,
)


LS = TEST_USERS["loan_servicer_headers"]


def test_ibr_monthly_payment_ca_borrower(api):
    """IBR variant on same borrower yields 35513 cents while SAVE yields 10513.

    PRD §3.5: "The multiplier is 1.50 for IBR and PAYE, and 2.25 for SAVE.
    From discretionary income, the annual obligation is 15% under IBR, 10% under
    PAYE, and 10% under SAVE."
    PRD §3.5: "Dividing the annual obligation by 12 yields the monthly amount
    in fractional cents; that figure is rounded half-up to integer cents and
    stored as monthly_payment_cents."

    Design: Difficulty/dual_variant_calc/idr_save_vs_ibr_same_borrower_diverge
    """
    borrower, loan, _ic = setup_idr_certified_borrower_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Jane Borrower", ssn_last4="1234",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2023-06-01T00:00:00Z",
        agi_cents=6_000_000, family_size=2, state_code="CA",
        income_effective_date="2026-05-01T00:00:00Z",
    )
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], loan["version"],
            plan_type="IBR", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    ibr_plan = validate_success(res, 201)
    assert ibr_plan["monthly_payment_cents"] == 35513, (
        f"IBR plan expected 35513 cents, got {ibr_plan['monthly_payment_cents']}"
    )


def test_save_monthly_payment_ca_borrower_diverges_from_ibr(api):
    """SAVE variant on the same borrower yields 10513 cents, distinctly lower
    than IBR's 35513 due to the 2.25 discretionary multiplier and 10% rate.

    PRD §3.5: "The multiplier is 1.50 for IBR and PAYE, and 2.25 for SAVE.
    From discretionary income, the annual obligation is 15% under IBR, 10% under
    PAYE, and 10% under SAVE."

    Design: Difficulty/dual_variant_calc/idr_save_vs_ibr_same_borrower_diverge
    """
    borrower, loan, _ic = setup_idr_certified_borrower_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Jane Borrower 2", ssn_last4="1235",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2023-06-01T00:00:00Z",
        agi_cents=6_000_000, family_size=2, state_code="CA",
        income_effective_date="2026-05-01T00:00:00Z",
    )
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], loan["version"],
            plan_type="SAVE", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    save_plan = validate_success(res, 201)
    assert save_plan["monthly_payment_cents"] == 10513, (
        f"SAVE plan expected 10513 cents, got {save_plan['monthly_payment_cents']}"
    )


def test_save_monthly_payment_alaska_borrower(api):
    """Alaska poverty table multi-input interaction: AK base 1_947_000 / per
    1_686_000 (sic — 686_000 per member) with SAVE plan AGI=6_000_000 family=2
    yields 631 cents.

    PRD §3.5: "in Alaska, a base of $19,470 (1947000 cents) and $6,860 (686000
    cents) per additional member"
    PRD §3.5: "The poverty line for the borrower is the base plus the per-member
    amount multiplied by the family size minus one."
    PRD §3.5: "The multiplier is 1.50 for IBR and PAYE, and 2.25 for SAVE.
    From discretionary income, the annual obligation is 15% under IBR, 10% under
    PAYE, and 10% under SAVE."

    Design: Difficulty/combinatorial_formula/idr_payment_mode_a_3_inputs_nonlinear
    """
    borrower, loan, _ic = setup_idr_certified_borrower_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="AK Borrower", ssn_last4="9991",
        loan_type="DIRECT_UNSUB", principal_cents=2_000_000,
        interest_rate_bps=500,
        disbursement_date="2023-06-01T00:00:00Z",
        agi_cents=6_000_000, family_size=2, state_code="AK",
        income_effective_date="2026-05-01T00:00:00Z",
    )
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], loan["version"],
            plan_type="SAVE", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    plan = validate_success(res, 201)
    assert plan["monthly_payment_cents"] == 631, (
        f"AK SAVE plan expected 631 cents, got {plan['monthly_payment_cents']}"
    )


def test_paye_monthly_payment_ca_borrower(api):
    """PAYE: AGI=6_000_000, family_size=2, CA → monthly = 23675 cents.

    PRD §3.5: "The multiplier is 1.50 for IBR and PAYE, and 2.25 for SAVE.
    From discretionary income, the annual obligation is 15% under IBR, 10% under
    PAYE, and 10% under SAVE."

    Design: Corner/calculations/idr_paye_correct_result
    """
    borrower, loan, _ic = setup_idr_certified_borrower_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Paye B", ssn_last4="0013",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2023-06-01T00:00:00Z",
        agi_cents=6_000_000, family_size=2, state_code="CA",
        income_effective_date="2026-05-01T00:00:00Z",
    )
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], loan["version"],
            plan_type="PAYE", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    plan = validate_success(res, 201)
    assert plan["monthly_payment_cents"] == 23675, (
        f"PAYE plan expected 23675 cents, got {plan['monthly_payment_cents']}"
    )


def test_standard_amortization_correct(api):
    """STANDARD: principal=3_000_000 cents, rate=533 bps over 120 months yields
    monthly_payment_cents = 32306.

    PRD §3.5: "For STANDARD, the engine ignores discretionary income and instead
    amortizes the principal figure (current principal_balance_cents plus
    capitalized_interest_cents) over 120 months using the loan's
    interest_rate_bps."
    PRD §3.5: "the monthly payment in fractional cents is the principal multiplied
    by the monthly rate divided by one minus one plus the monthly rate raised to
    the power negative one hundred and twenty; that fractional figure is rounded
    half-up to integer cents to produce monthly_payment_cents."

    Design: Corner/calculations/idr_standard_amortization_correct_result
    """
    # STANDARD does not require a certified income certification — the formula
    # only uses principal and rate.
    from test_helpers import set_clock, create_borrower, create_loan, walk_loan_to_repayment
    set_clock("2026-06-01T00:00:00Z")
    borrower = create_borrower(full_name="Std B", ssn_last4="0014")
    loan = create_loan(
        borrower["id"], loan_type="DIRECT_UNSUB",
        principal_cents=3_000_000, interest_rate_bps=533,
        disbursement_date="2023-06-01T00:00:00Z",
    )
    loan = walk_loan_to_repayment(loan["id"])
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], loan["version"],
            plan_type="STANDARD", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    plan = validate_success(res, 201)
    assert plan["monthly_payment_cents"] == 32306, (
        f"STANDARD plan expected 32306 cents, got {plan['monthly_payment_cents']}"
    )


def test_idr_zero_discretionary_floor(api):
    """When AGI is below the 1.50 × poverty threshold for IBR, discretionary
    clamps to zero, and monthly_payment_cents is 0.

    PRD §3.5: "The engine then computes annual discretionary income as the
    borrower's agi minus a multiplier times the poverty line, clipped to zero
    when the subtraction would otherwise be negative."

    Design: Corner/calculations/idr_zero_discretionary_floor
    """
    borrower, loan, _ic = setup_idr_certified_borrower_in_repayment(
        clock_iso="2026-06-01T00:00:00Z",
        full_name="Zero B", ssn_last4="0015",
        loan_type="DIRECT_UNSUB", principal_cents=3_000_000,
        interest_rate_bps=533,
        disbursement_date="2023-06-01T00:00:00Z",
        agi_cents=1_500_000, family_size=2, state_code="CA",
        income_effective_date="2026-05-01T00:00:00Z",
    )
    res = api.create_repayment_plan(
        create_repayment_plan_payload(
            loan["id"], loan["version"],
            plan_type="IBR", effective_date="2026-06-01T00:00:00Z"),
        LS,
    )
    plan = validate_success(res, 201)
    assert plan["monthly_payment_cents"] == 0, (
        f"IBR plan expected 0 cents (zero discretionary), "
        f"got {plan['monthly_payment_cents']}"
    )
