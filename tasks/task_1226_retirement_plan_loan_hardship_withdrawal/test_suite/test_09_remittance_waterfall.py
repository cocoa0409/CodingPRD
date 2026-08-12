"""Payroll remittance waterfall: pinned ordering, eligibility filtering, exact
reversal, and explicit allocation mismatch (PRD §3.6)."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
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
    list_loan_tasks,
    make_participant_headers,
    request_loan,
    set_clock,
    setup_disbursed_loan,
    setup_plan_and_participant,
    setup_repaid_loan,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


# ---------------------------------------------------------------------------
# Corner: waterfall_orders_missed_first_then_pending_by_due_date
# ---------------------------------------------------------------------------


def test_waterfall_orders_missed_first_then_pending_by_due_date(api):
    """PRD §3.6: "Funds are applied in a pinned order: `MISSED` installments
    first, then `PENDING`; within each group by ascending `due_date`, then by the
    owning loan's ascending `created_at`, then by ascending `installment_number`."

    Design: Corner/calculations/waterfall_orders_missed_first_then_pending_by_due_date
    """
    plan = validate_success(
        api.create_plan(
            create_plan_payload(name="Plan WF", max_loans_outstanding=2), ADMIN
        ),
        201,
    )
    participant = enroll_participant(plan["id"], vested_balance_cents=20_000_000)
    # Loan A 500,000c / 12mo disbursed first
    loan_a = request_loan(participant, principal_amount_cents=500_000, term_months=12)
    approve_loan_fully(loan_a["id"])
    validate_success(api.disburse_loan(loan_a["id"], ADMIN), 200)
    # Loan B 300,000c / 12mo disbursed second
    loan_b = request_loan(participant, principal_amount_cents=300_000, term_months=12)
    approve_loan_fully(loan_b["id"])
    validate_success(api.disburse_loan(loan_b["id"], ADMIN), 200)
    # Both installment 1 rows (due 2026-06-01) become MISSED
    set_clock("2026-06-02T00:00:00Z")
    # 111,290c = A1 (42,804) + B1 (25,682) + A2 (42,804)
    remit = validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=111_290, pay_date="2026-06-02T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    applied = remit["applied_allocations"]
    assert len(applied) == 3
    # [0] loan A installment 1 (MISSED)
    assert applied[0]["loan_id"] == loan_a["id"]
    assert applied[0]["amount_cents"] == 42_804
    assert applied[0]["to_interest_cents"] == 2_083
    assert applied[0]["to_principal_cents"] == 40_721
    # [1] loan B installment 1 (MISSED)
    assert applied[1]["loan_id"] == loan_b["id"]
    assert applied[1]["amount_cents"] == 25_682
    # [2] loan A installment 2 (PENDING, paid early)
    assert applied[2]["loan_id"] == loan_a["id"]
    assert applied[2]["amount_cents"] == 42_804
    # Both loans cured
    a_now = validate_success(api.get_loan(loan_a["id"], ADMIN), 200)
    b_now = validate_success(api.get_loan(loan_b["id"], ADMIN), 200)
    assert a_now["outstanding_principal_cents"] == 418_389
    assert a_now["delinquency_status"] == "CURRENT"
    assert b_now["outstanding_principal_cents"] == 275_568
    assert b_now["delinquency_status"] == "CURRENT"


# ---------------------------------------------------------------------------
# Corner: waterfall_excludes_terminal_and_deemed_loans
# ---------------------------------------------------------------------------


def test_waterfall_excludes_terminal_and_deemed_loans(api):
    """PRD §3.6: "When the posting supplies explicit `allocations` — a list of
    loan-and-amount pairs — the amounts must sum exactly to `amount_cents`,
    failing which the posting is rejected with `ERR_REMITTANCE_AMOUNT_MISMATCH`;
    every referenced loan must belong to the eligible set just defined, failing
    which the rejection is `ERR_INVALID_STATE`." The eligible set excludes REPAID
    loans (PRD §3.6: "loans already `REPAID`, `REFINANCED`, or `OFFSET` are out
    of scope").

    Design: Corner/calculations/waterfall_excludes_terminal_and_deemed_loans
    """
    _, participant, loan, _, _ = setup_repaid_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    res = api.create_remittance(
        participant["id"],
        {
            "amount_cents": 10_000,
            "pay_date": "2026-06-03T00:00:00Z",
            "allocations": [{"loan_id": loan["id"], "amount_cents": 10_000}],
        },
        PAYROLL,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_after["lifecycle_status"] == "REPAID"
    assert loan_after["outstanding_principal_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: remittance_allocation_sum_mismatch_rejected
# ---------------------------------------------------------------------------


def test_remittance_allocation_sum_mismatch_rejected(api):
    """PRD §3.6: "When the posting supplies explicit `allocations` — a list of
    loan-and-amount pairs — the amounts must sum exactly to `amount_cents`,
    failing which the posting is rejected with `ERR_REMITTANCE_AMOUNT_MISMATCH`".

    Design: Corner/calculations/remittance_allocation_sum_mismatch_rejected
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    # 40,000 + 45,000 = 85,000 != amount_cents 85,607
    res = api.create_remittance(
        participant["id"],
        {
            "amount_cents": 85_607,
            "pay_date": "2026-05-15T00:00:00Z",
            "allocations": [
                {"loan_id": loan["id"], "amount_cents": 40_000},
                {"loan_id": loan["id"], "amount_cents": 45_000},
            ],
        },
        PAYROLL,
    )
    validate_error(
        res, ApiErrorId.ERR_REMITTANCE_AMOUNT_MISMATCH, expected_status=422
    )
    # Nothing applied — outstanding unchanged
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_after["outstanding_principal_cents"] == 1_000_000


# ---------------------------------------------------------------------------
# Difficulty: remittance_post_then_reverse_conserves_outstanding_principal
# ---------------------------------------------------------------------------


def test_remittance_post_then_reverse_conserves_outstanding_principal_post(api):
    """PRD §3.5: "`outstanding_principal_cents` is the original principal minus
    the principal applied by non-reversed remittances, where each installment's
    principal coverage is the portion of its `paid_amount_cents` exceeding its
    `interest_portion_cents`, never below zero."

    Design: Difficulty/compensating_invariant/remittance_post_then_reverse_conserves_outstanding_principal
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    assert loan["outstanding_principal_cents"] == 1_000_000
    remit = validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-05-15T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    # 85,607c covers installment 1 (4,167 interest + 81,440 principal)
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_after["outstanding_principal_cents"] == 918_560


def test_remittance_post_then_reverse_conserves_outstanding_principal_reverse(api):
    """PRD §3.6: "otherwise the remittance moves from `POSTED` to `REVERSED` and
    the server undoes `applied_allocations` exactly, decrementing each referenced
    installment's `paid_amount_cents` by its recorded amount."

    Design: Difficulty/compensating_invariant/remittance_post_then_reverse_conserves_outstanding_principal
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    remit = validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-05-15T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    reversed_remit = validate_success(
        api.reverse_remittance(remit["id"], ADMIN), 200
    )
    assert reversed_remit["status"] == "REVERSED"

    loan_final = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_final["outstanding_principal_cents"] == 1_000_000

    inst, _ = validate_paginated(
        api.list_loan_installments(loan["id"], ADMIN)
    )
    assert inst[0]["status"] == "PENDING"
    assert inst[0]["paid_amount_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: loan_auto_repaid_when_outstanding_hits_zero
# ---------------------------------------------------------------------------


def test_loan_auto_repaid_when_outstanding_hits_zero(api):
    """PRD §3.6: "When a posting drives `outstanding_principal_cents` to exactly
    zero, the loan moves from `DISBURSED` to `REPAID`, and its remaining
    `PENDING` installments are `CLOSED` while `MISSED` and `CURED` rows retain
    their history."

    Design: Corner/state_machines/loan_auto_repaid_when_outstanding_hits_zero
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=1_027_289, pay_date="2026-05-15T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_after["lifecycle_status"] == "REPAID"
    assert loan_after["outstanding_principal_cents"] == 0
    inst, _ = validate_paginated(
        api.list_loan_installments(loan["id"], ADMIN, params={"limit": 100})
    )
    # All 12 installments were fully covered by the payoff
    assert inst[0]["status"] == "PAID"
    assert inst[11]["status"] == "PAID"


# ---------------------------------------------------------------------------
# Corner: reverse_reversed_remittance_returns_invalid_state
# ---------------------------------------------------------------------------


def test_reverse_reversed_remittance_returns_invalid_state(api):
    """PRD §3.6: "Reversing a remittance that already stands `REVERSED` fails
    with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/reverse_reversed_remittance_returns_invalid_state
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    remit = validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-05-15T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    validate_success(api.reverse_remittance(remit["id"], ADMIN), 200)
    # Second reverse is rejected
    res = api.reverse_remittance(remit["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    remit_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)  # ensure state stable
    final = api.list_participant_remittances(participant["id"], ADMIN).json()["data"][0]
    assert final["status"] == "REVERSED"
