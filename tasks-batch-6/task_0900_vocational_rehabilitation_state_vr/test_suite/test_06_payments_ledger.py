"""Payments, the case fund ledger, the dual obligation/expenditure views, and the
federal/state reimbursement split.

Difficulty queue (§1.8): dual_variant_calc / case_fund_obligation_vs_expenditure;
combinatorial_formula / payment_federal_split_round_then_sum_mode_b;
compensating_invariant / money_conserved_approve_then_cancel.
Corner queue (§1.9): payment validations and the ISSUED-void compensating reversal.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_services_active_case, request_and_approve_authorization,
    create_pending_payment, create_issued_payment, create_payment_payload,
    assert_case_ledger_invariant, TEST_USERS,
)

VRADMIN = TEST_USERS["vradmin_headers"]
FISCAL = TEST_USERS["fiscal_officer_headers"]


# ─── Difficulty: obligation vs expenditure on the case ledger ────────

def test_case_ledger_after_partial_payment_issue(api):
    """PRD §2.8: "`funds_available_cents` is `budget_allocated_cents` minus
    `funds_committed_cents` minus `funds_paid_cents`."
    PRD §3.7: "`funds_committed_cents` falls by `amount_cents` while
    `funds_paid_cents` rises by `amount_cents`, incrementing the case's `version`".

    Design: Difficulty/dual_variant_calc/case_fund_obligation_vs_expenditure
    """
    ctx = setup_services_active_case(monthly_income_cents=300000, budget_allocated_cents=1000000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=500000, comparable_benefit_cents=100000)
    assert approved["agency_share_cents"] == 360000
    create_issued_payment(approved["id"], 100000)
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["funds_committed_cents"] == 260000
    assert case["funds_paid_cents"] == 100000
    assert case["funds_available_cents"] == 640000
    assert_case_ledger_invariant(case)


def test_total_obligation_diverges_from_total_expenditure(api):
    """PRD §2.8: "The **total obligation** (budget-exposure / encumbrance view) is
    `funds_committed_cents` plus `funds_paid_cents` — money still owed plus money
    already spent. The **total expenditure** (cash-out / RSA-911 view) is
    `funds_paid_cents` alone; it excludes still-committed obligations and therefore
    diverges from total obligation whenever any committed balance remains."

    Design: Difficulty/dual_variant_calc/case_fund_obligation_vs_expenditure
    """
    ctx = setup_services_active_case(monthly_income_cents=300000, budget_allocated_cents=1000000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=500000, comparable_benefit_cents=100000)
    create_issued_payment(approved["id"], 100000)
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    total_obligation = case["funds_committed_cents"] + case["funds_paid_cents"]
    total_expenditure = case["funds_paid_cents"]
    assert total_obligation == 360000
    assert total_expenditure == 100000
    assert total_obligation != total_expenditure


# ─── Difficulty: federal split rounded per line, then summed (mode b) ─

def test_payment_federal_split_per_payment_rounding(api):
    """PRD §3.7: "`federal_share_cents` is `amount_cents` multiplied by the federal
    match rate of 0.787, rounded half up to whole cents, and `state_share_cents` is
    `amount_cents` minus `federal_share_cents`."

    Design: Difficulty/combinatorial_formula/payment_federal_split_round_then_sum_mode_b
    """
    ctx = setup_services_active_case(monthly_income_cents=150000, budget_allocated_cents=500000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=200000, comparable_benefit_cents=0)
    pay1 = create_issued_payment(approved["id"], 100)
    pay2 = create_issued_payment(approved["id"], 100)
    assert pay1["federal_share_cents"] == 79
    assert pay1["state_share_cents"] == 21
    assert pay2["federal_share_cents"] == 79
    assert pay2["state_share_cents"] == 21


def test_rsa911_totals_round_then_sum(api):
    """PRD §3.7: "the already-rounded `federal_share_cents` of each `ISSUED` payment
    are summed to give the case's total federal expenditure, and likewise the
    `state_share_cents` are summed for the total state expenditure. These totals are
    the sums of the per-payment rounded shares, not the result of applying the match
    rate to a grand total — round each line first, then add."

    Design: Difficulty/combinatorial_formula/payment_federal_split_round_then_sum_mode_b
    """
    ctx = setup_services_active_case(monthly_income_cents=150000, budget_allocated_cents=500000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=200000, comparable_benefit_cents=0)
    create_issued_payment(approved["id"], 100)
    create_issued_payment(approved["id"], 100)
    rsa = validate_success(api.get_rsa911(ctx["case_id"], ctx["supervisor_headers"]), 200)
    assert rsa["total_federal_expenditure_cents"] == 158   # 79 + 79, not round(200 * 0.787) == 157
    assert rsa["total_state_expenditure_cents"] == 42       # 21 + 21


# ─── Difficulty: money conserved across approve then cancel ──────────

def test_money_conserved_after_cancel(api):
    """PRD §3.6: "The still-owed remainder — `agency_share_cents` minus
    `amount_paid_cents` — is released: the case's `funds_committed_cents` falls by
    that remainder and its `funds_available_cents` rises by it, incrementing the
    case's `version`."

    Design: Difficulty/compensating_invariant/money_conserved_approve_then_cancel
    """
    ctx = setup_services_active_case(monthly_income_cents=300000, budget_allocated_cents=1000000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=500000, comparable_benefit_cents=100000)
    validate_success(api.cancel_authorization(approved["id"], ctx["counselor_headers"]), 200)
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["funds_committed_cents"] == 0
    assert case["funds_paid_cents"] == 0
    assert case["funds_available_cents"] == 1000000


def test_budget_conservation_invariant_holds_before_and_after_cancel(api):
    """PRD §2.8: "`funds_available_cents` is `budget_allocated_cents` minus
    `funds_committed_cents` minus `funds_paid_cents`."

    Design: Difficulty/compensating_invariant/money_conserved_approve_then_cancel
    """
    ctx = setup_services_active_case(monthly_income_cents=300000, budget_allocated_cents=1000000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=500000, comparable_benefit_cents=100000)
    committed = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert_case_ledger_invariant(committed)
    assert committed["budget_allocated_cents"] == 1000000

    api.cancel_authorization(approved["id"], ctx["counselor_headers"])
    released = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert_case_ledger_invariant(released)
    assert released["budget_allocated_cents"] == 1000000


# ─── Corner: payment validations + ISSUED void reversal ──────────────

def test_payment_amount_zero_not_positive(api):
    """PRD §3.7: "A `FiscalOfficer` creates a payment against an authorization by
    supplying the `authorization_id` and an `amount_cents` greater than zero (else
    `ERR_AMOUNT_NOT_POSITIVE`)."

    Design: Corner/validations/payment_amount_zero_not_positive
    """
    ctx = setup_services_active_case(monthly_income_cents=150000, budget_allocated_cents=500000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=100000)
    res = api.create_payment(create_payment_payload(approved["id"], amount_cents=0), FISCAL)
    validate_error(res, "ERR_AMOUNT_NOT_POSITIVE")


def test_payment_exceeds_authorization_remaining(api):
    """PRD §3.7: "A payment amount may not exceed the authorization's remaining
    obligation — `agency_share_cents` minus `amount_paid_cents` — or it is rejected
    with `ERR_PAYMENT_EXCEEDS_AUTHORIZATION`."

    Design: Corner/validations/payment_exceeds_authorization_remaining
    """
    ctx = setup_services_active_case(monthly_income_cents=150000, budget_allocated_cents=500000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=100000)
    res = api.create_payment(create_payment_payload(approved["id"], amount_cents=200000), FISCAL)
    validate_error(res, "ERR_PAYMENT_EXCEEDS_AUTHORIZATION")


def test_payment_void_issued_compensating_reversal(api):
    """PRD §3.7: "Voiding an already-`ISSUED` payment is a compensating reversal: the
    payment moves to `VOIDED`, the case's `funds_paid_cents` falls by `amount_cents`
    while `funds_committed_cents` rises by `amount_cents` (incrementing the case's
    `version`), the provider's `ledger_paid_cents` falls by `amount_cents`
    (incrementing the provider's `version`), and the authorization's
    `amount_paid_cents` falls by `amount_cents`."

    Design: Corner/state_machines/payment_void_issued_compensating_reversal
    """
    ctx = setup_services_active_case(monthly_income_cents=150000, budget_allocated_cents=500000)
    approved = request_and_approve_authorization(ctx, authorized_amount_cents=100000)
    payment = create_issued_payment(approved["id"], 100000)
    voided = validate_success(api.void_payment(payment["id"], FISCAL), 200)
    assert voided["status"] == "VOIDED"
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["funds_paid_cents"] == 0
    assert case["funds_committed_cents"] == 100000
    provider = validate_success(api.get_provider(ctx["provider_id"], VRADMIN), 200)
    assert provider["ledger_paid_cents"] == 0
