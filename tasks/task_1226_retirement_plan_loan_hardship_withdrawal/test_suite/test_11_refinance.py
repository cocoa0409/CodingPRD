"""Refinancing: max-loans boundary, lookback window, plan posture, conserved
principal invariant, and priority-6-beats-priority-12 conflict (PRD §3.8)."""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_loan_fully,
    create_loan_payload,
    create_plan_payload,
    create_remittance_payload,
    enroll_participant,
    make_participant_headers,
    refinance_loan_payload,
    request_loan,
    set_clock,
    setup_disbursed_loan,
    setup_plan_and_participant,
    setup_repaid_loan,
    update_plan_policy_payload,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


# ---------------------------------------------------------------------------
# Difficulty: refinance_at_max_loans_outstanding_boundary
# ---------------------------------------------------------------------------


def test_refinance_at_max_loans_outstanding_boundary_fresh_request_rejected(api):
    """PRD §2.8 priority 11: "the count of the participant's loans in
    `REQUESTED`, `APPROVED`, or `DISBURSED` is below the plan's
    `max_loans_outstanding` (otherwise `ERR_MAX_LOANS_OUTSTANDING`)"."

    Design: Difficulty/boundary_precision_check/refinance_at_max_loans_outstanding_boundary
    """
    plan, participant, loan = setup_disbursed_loan(
        principal_amount_cents=500_000,
        term_months=12,
        vested_balance_cents=10_000_000,
        plan_overrides={
            "allows_refinance": True,
            "refinance_min_months_since_disbursement": 0,
        },
    )
    # A fresh loan request at count==max is rejected
    res = api.create_loan(
        participant["id"],
        create_loan_payload(principal_amount_cents=100_000, term_months=12),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_MAX_LOANS_OUTSTANDING, expected_status=422)


def test_refinance_at_max_loans_outstanding_boundary_refinance_succeeds(api):
    """PRD §3.8: "The operation is atomic and a replacement rather than an
    addition: the old loan leaves the set counted by `max_loans_outstanding` at
    the same moment the new one enters it, so the refinance itself never
    breaches the multiple-loan policy."

    Design: Difficulty/boundary_precision_check/refinance_at_max_loans_outstanding_boundary
    """
    plan, participant, loan = setup_disbursed_loan(
        principal_amount_cents=500_000,
        term_months=12,
        vested_balance_cents=10_000_000,
        plan_overrides={
            "allows_refinance": True,
            "refinance_min_months_since_disbursement": 0,
        },
    )
    # Refinance succeeds even at count == max
    new_loan = validate_success(
        api.refinance_loan(loan["id"], refinance_loan_payload(cash_out_cents=0), ADMIN),
        201,
    )
    assert new_loan["lifecycle_status"] == "DISBURSED"
    # new principal = 500,000 outstanding + 0 accrued due + 0 cash-out + 10,000 fee
    assert new_loan["principal_amount_cents"] == 510_000
    old = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert old["lifecycle_status"] == "REFINANCED"
    assert old["outstanding_principal_cents"] == 0
    # Count of loans in {REQUESTED, APPROVED, DISBURSED} is still exactly 1
    from prd_bench_local_runner.testing import validate_paginated
    loans, _ = validate_paginated(api.list_participant_loans(participant["id"], ADMIN))
    active_count = sum(
        1 for l in loans
        if l["lifecycle_status"] in ("REQUESTED", "APPROVED", "DISBURSED")
    )
    assert active_count == 1


# ---------------------------------------------------------------------------
# Difficulty: refinance_lookback_window_violation
# ---------------------------------------------------------------------------


def _setup_lookback_scenario(api):
    """Plan with allows_refinance + 2-month lookback; 500,000c / 12mo loan
    disbursed at clock 2026-05-01."""
    return setup_disbursed_loan(
        principal_amount_cents=500_000,
        term_months=12,
        vested_balance_cents=10_000_000,
        plan_overrides={
            "allows_refinance": True,
            "refinance_min_months_since_disbursement": 2,
        },
    )


def test_refinance_lookback_window_violation_too_early(api):
    """PRD §3.8: "at least `refinance_min_months_since_disbursement` whole
    calendar months must have elapsed since the old loan's `disbursed_on`
    (`ERR_REFINANCE_LOOKBACK_VIOLATION`)"."

    Design: Difficulty/resource_temporal_overlap/refinance_lookback_window_violation
    """
    _, participant, loan = _setup_lookback_scenario(api)
    set_clock("2026-06-15T00:00:00Z")
    res = api.refinance_loan(
        loan["id"], refinance_loan_payload(cash_out_cents=0), ADMIN
    )
    validate_error(
        res, ApiErrorId.ERR_REFINANCE_LOOKBACK_VIOLATION, expected_status=422
    )


def test_refinance_lookback_window_violation_at_boundary_succeeds(api):
    """PRD §3.8: "The new principal is the old loan's `outstanding_principal_cents`
    plus the accrued unpaid interest due through the logical clock date — computed
    exactly as the interest component of the taxable-amount formula with that
    cutoff — plus the supplied `cash_out_cents`, plus a flat refinance fee of
    10,000 cents (one hundred dollars)."

    Design: Difficulty/resource_temporal_overlap/refinance_lookback_window_violation
    """
    _, participant, loan = _setup_lookback_scenario(api)
    set_clock("2026-06-15T00:00:00Z")  # one missed installment
    set_clock("2026-07-01T00:00:00Z")  # exactly 2 months after 2026-05-01 disb
    new_loan = validate_success(
        api.refinance_loan(loan["id"], refinance_loan_payload(cash_out_cents=0), ADMIN),
        201,
    )
    # 500,000 outstanding + 2,083 (i1 int due 06-01) + 1,914 (i2 int due 07-01)
    # + 0 cash + 10,000 fee = 513,997
    assert new_loan["principal_amount_cents"] == 513_997


# ---------------------------------------------------------------------------
# Difficulty: refinance_conserves_total_outstanding_modulo_cashout_and_fee
# ---------------------------------------------------------------------------


def test_refinance_conserves_total_outstanding_modulo_cashout_and_fee_delta(api):
    """PRD §3.8: "A conserved-quantity invariant pins the accounting — the sum of
    `outstanding_principal_cents` over the participant's loans after the
    refinance, minus the same sum before it, equals exactly `cash_out_cents` plus
    the refinance fee."

    Design: Difficulty/compensating_invariant/refinance_conserves_total_outstanding_modulo_cashout_and_fee
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000,
        term_months=12,
        vested_balance_cents=10_000_000,
        plan_overrides={
            "allows_refinance": True,
            "refinance_min_months_since_disbursement": 0,
        },
    )
    # Pay installment 1 -> outstanding drops to 918,560
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-06-01T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    before = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert before["outstanding_principal_cents"] == 918_560

    new_loan = validate_success(
        api.refinance_loan(loan["id"], refinance_loan_payload(cash_out_cents=0), ADMIN),
        201,
    )
    # 918,560 + 0 accrued due + 0 cash-out + 10,000 fee
    assert new_loan["principal_amount_cents"] == 928_560
    assert new_loan["outstanding_principal_cents"] == 928_560
    old_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert old_after["outstanding_principal_cents"] == 0
    # Conserved delta: (928,560 + 0) - 918,560 = 10,000 = cash_out + REFI_FEE
    delta = (new_loan["outstanding_principal_cents"]
             + old_after["outstanding_principal_cents"]
             - before["outstanding_principal_cents"])
    assert delta == 10_000


def test_refinance_conserves_total_outstanding_modulo_cashout_and_fee_lineage(api):
    """PRD §3.8: "The new loan is created already `DISBURSED`, with
    `refinances_loan_id` pointing at the loan it replaces".

    Design: Difficulty/compensating_invariant/refinance_conserves_total_outstanding_modulo_cashout_and_fee
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000,
        term_months=12,
        vested_balance_cents=10_000_000,
        plan_overrides={
            "allows_refinance": True,
            "refinance_min_months_since_disbursement": 0,
        },
    )
    # Pay installment 1 to get a non-trivial refinance scenario
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-06-01T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    new_loan = validate_success(
        api.refinance_loan(loan["id"], refinance_loan_payload(cash_out_cents=0), ADMIN),
        201,
    )
    assert new_loan["refinances_loan_id"] == loan["id"]
    old = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert old["lifecycle_status"] == "REFINANCED"


# ---------------------------------------------------------------------------
# Difficulty: state_beats_fiscal_on_refinance_over_limit
# ---------------------------------------------------------------------------


def test_state_beats_fiscal_on_refinance_over_limit_state_leg(api):
    """PRD §2.8 priority 6 (from-state validity) is checked before priority 12
    (fiscal): "Every request is evaluated against a fixed cascade of check groups,
    applied in the priority order below; the first failing group determines the
    error response, and later groups are not consulted." A REPAID loan cannot be
    refinanced regardless of the cash_out amount.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_refinance_over_limit
    """
    plan, participant, loan, _, _ = setup_repaid_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    # Enable refinance via policy PUT so the allows_refinance gate doesn't fire first
    plan_fresh = validate_success(api.get_plan(plan["id"], ADMIN), 200)
    validate_success(
        api.update_plan_policy(
            plan["id"],
            update_plan_policy_payload(
                plan_fresh["version"],
                allows_refinance=True,
                refinance_min_months_since_disbursement=0,
            ),
            ADMIN,
        ),
        200,
    )
    res = api.refinance_loan(
        loan["id"], refinance_loan_payload(cash_out_cents=9_000_000), ADMIN
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_state_beats_fiscal_on_refinance_over_limit_fiscal_would_also_fail(api):
    """PRD §2.8 priority 6: "From-state validity. The target resource is in a
    valid from-state for the requested transition. ... all other from-state
    failures carry `ERR_INVALID_STATE`." Even when the cash_out would breach the
    fiscal limit, the from-state failure wins.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_refinance_over_limit
    """
    plan, participant, loan, _, _ = setup_repaid_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    plan_fresh = validate_success(api.get_plan(plan["id"], ADMIN), 200)
    validate_success(
        api.update_plan_policy(
            plan["id"],
            update_plan_policy_payload(
                plan_fresh["version"],
                allows_refinance=True,
                refinance_min_months_since_disbursement=0,
            ),
            ADMIN,
        ),
        200,
    )
    res = api.refinance_loan(
        loan["id"], refinance_loan_payload(cash_out_cents=9_000_000), ADMIN
    )
    # Must be the state error, not the fiscal one
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    body = res.json()
    assert body["data"]["error_id"] == "ERR_INVALID_STATE"


# ---------------------------------------------------------------------------
# Corner: refinance_disabled_by_plan_policy
# ---------------------------------------------------------------------------


def test_refinance_disabled_by_plan_policy(api):
    """PRD §3.8: "The refinance is gated in cascade order: the plan's
    `allows_refinance` must be true (`ERR_REFINANCE_NOT_ALLOWED`); the loan's
    delinquency must not stand `DEEMED` (`ERR_INVALID_STATE`); at least
    `refinance_min_months_since_disbursement` whole calendar months must have
    elapsed since the old loan's `disbursed_on`
    (`ERR_REFINANCE_LOOKBACK_VIOLATION`); and the new principal must not exceed
    the participant's computed maximum loan amount — high-water reduction
    included — (`ERR_LOAN_LIMIT_EXCEEDED`)."

    Design: Corner/validations/refinance_disabled_by_plan_policy
    """
    # Plan defaults allows_refinance=False; set lookback to 0 so only the flag
    # is under test.
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=500_000,
        term_months=12,
        vested_balance_cents=10_000_000,
        plan_overrides={"refinance_min_months_since_disbursement": 0},
    )
    res = api.refinance_loan(
        loan["id"], refinance_loan_payload(cash_out_cents=0), ADMIN
    )
    validate_error(res, ApiErrorId.ERR_REFINANCE_NOT_ALLOWED, expected_status=422)
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_after["lifecycle_status"] == "DISBURSED"
