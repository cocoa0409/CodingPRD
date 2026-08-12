"""Delinquency lifecycle: parallel dimensions, deemed cascade, offset cascade,
and variant-specific taxable cutoffs (PRD §3.6, §3.7, §3.2)."""
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
    make_participant_headers,
    request_loan,
    set_clock,
    setup_disbursed_loan,
    setup_plan_and_participant,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


# ---------------------------------------------------------------------------
# Difficulty: loan_parallel_dimensions_and_repaid_revert_cycle
# ---------------------------------------------------------------------------


def test_loan_parallel_dimensions_and_repaid_revert_cycle_cure(api):
    """PRD §3.6: "a covered `MISSED` installment becomes `CURED` provided the
    remittance's `pay_date` falls on or before `cure_deadline_on`, and when every
    missed installment is cured within that deadline the loan's delinquency
    returns from `DELINQUENT` to `CURRENT` and `cure_deadline_on` clears to
    null."

    Design: Difficulty/non_linear_state_machine/loan_parallel_dimensions_and_repaid_revert_cycle
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    # Miss installment 1 (due 2026-06-01) -> DELINQUENT
    set_clock("2026-06-02T00:00:00Z")
    mid = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert mid["lifecycle_status"] == "DISBURSED"
    assert mid["delinquency_status"] == "DELINQUENT"
    # Cure with pay_date at the deadline (inclusive)
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-09-30T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    cured = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert cured["delinquency_status"] == "CURRENT"
    inst, _ = validate_paginated(api.list_loan_installments(loan["id"], ADMIN))
    assert inst[0]["status"] == "CURED"


def test_loan_parallel_dimensions_and_repaid_revert_cycle_revert(api):
    """PRD §3.6: "The loan's `outstanding_principal_cents` is recomputed, and a
    loan that had reached `REPAID` returns to `DISBURSED` when outstanding
    principal is restored above zero — in that case each `CLOSED` row whose
    `paid_amount_cents` again falls short of `scheduled_amount_cents` returns to
    `PENDING`. ... an unpaid row whose `due_date` has passed becomes `MISSED`
    again ... a cure may be undone, moving the loan from `CURRENT` back to
    `DELINQUENT`".

    Design: Difficulty/non_linear_state_machine/loan_parallel_dimensions_and_repaid_revert_cycle
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    # Miss installment 1, then cure it
    set_clock("2026-06-02T00:00:00Z")
    validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=85_607, pay_date="2026-09-30T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    # Pay off the remaining 941,682c at 2026-10-01 -> REPAID
    set_clock("2026-10-01T00:00:00Z")
    payoff = validate_success(
        api.create_remittance(
            participant["id"],
            create_remittance_payload(
                amount_cents=941_682, pay_date="2026-10-01T00:00:00Z"
            ),
            PAYROLL,
        ),
        201,
    )
    repaid = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert repaid["lifecycle_status"] == "REPAID"
    assert repaid["delinquency_status"] == "CURRENT"
    # Reverse the payoff -> back to DISBURSED, delinquency recomputed
    validate_success(api.reverse_remittance(payoff["id"], ADMIN), 200)
    final = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert final["lifecycle_status"] == "DISBURSED"
    assert final["outstanding_principal_cents"] == 918_560
    assert final["delinquency_status"] == "DELINQUENT"
    inst, _ = validate_paginated(
        api.list_loan_installments(loan["id"], ADMIN, params={"limit": 100})
    )
    # Installment 1 keeps its CURED history; installment 2 (due 2026-07-01) is
    # MISSED again; installment 6 (due 2026-11-01) is still PENDING.
    assert inst[0]["status"] == "CURED"
    assert inst[1]["status"] == "MISSED"
    assert inst[5]["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Difficulty: cure_expiry_cascade_deemed_tax_event_eligibility_lock
# ---------------------------------------------------------------------------


def test_cure_expiry_cascade_deemed_status_and_tax_event(api):
    """PRD §3.7: "the deemed distribution fires in four links. First, the loan's
    delinquency moves to `DEEMED` and `deemed_on` is stamped with the logical
    clock date ... Second, the transition itself creates a `TaxEvent` whose
    `source_type` is `LOAN_DEEMED`, whose `event_date` is `deemed_on`, and whose
    taxable amount follows the deemed variant below."

    Design: Difficulty/transitive_cascade/cure_expiry_cascade_deemed_tax_event_eligibility_lock
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    set_clock("2026-06-02T00:00:00Z")  # installment 1 MISSED, deadline 2026-09-30
    set_clock("2026-10-01T00:00:00Z")  # past deadline -> deemed
    loan_now = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_now["delinquency_status"] == "DEEMED"
    assert loan_now["lifecycle_status"] == "DISBURSED"  # parallel dimensions

    tax_events, _ = validate_paginated(
        api.list_participant_tax_events(participant["id"], ADMIN)
    )
    assert len(tax_events) == 1
    ev = tax_events[0]
    assert ev["source_type"] == "LOAN_DEEMED"
    # Deemed cutoff = 2026-09-30 -> 4 unpaid due interest portions
    # 4,167 + 3,827 + 3,487 + 3,144 = 14,625; taxable = 1,000,000 + 14,625
    assert ev["taxable_amount_cents"] == 1_014_625
    assert ev["tax_year"] == 2026


def test_cure_expiry_cascade_sets_participant_ytd_and_locks_eligibility(api):
    """PRD §3.7: "the created event adds its `taxable_amount_cents` into the
    participant's `ytd_taxable_distributions_cents` and sets
    `loan_eligibility_locked_until` to `deemed_on` plus twelve calendar months.
    Fourth, while the logical clock remains earlier than that lock, any new loan
    request by the participant is rejected with `ERR_LOAN_ELIGIBILITY_LOCKED`."

    Design: Difficulty/transitive_cascade/cure_expiry_cascade_deemed_tax_event_eligibility_lock
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    set_clock("2026-06-02T00:00:00Z")
    set_clock("2026-10-01T00:00:00Z")  # deemed_on = 2026-10-01
    participant_after = validate_success(
        api.get_participant(participant["id"], ADMIN), 200
    )
    assert participant_after["ytd_taxable_distributions_cents"] == 1_014_625
    assert (
        participant_after["loan_eligibility_locked_until"]
        == "2027-10-01T00:00:00Z"
    )
    # New loan request while clock < lock is rejected
    res = api.create_loan(
        participant["id"],
        create_loan_payload(principal_amount_cents=100_000, term_months=12),
        make_participant_headers(participant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LOAN_ELIGIBILITY_LOCKED, expected_status=422)


# ---------------------------------------------------------------------------
# Difficulty: termination_offset_cascade_tax_events
# ---------------------------------------------------------------------------


def test_termination_offset_cascade_tax_events_loan_offset(api):
    """PRD §3.2: "each of the participant's loans standing `DISBURSED` with
    `outstanding_principal_cents` above zero is processed in ascending
    `created_at` order and moved to `OFFSET`, and each offset loan's remaining
    `PENDING` and `MISSED` installments are `CLOSED`. Second, each offset
    transition itself creates a `TaxEvent` whose `source_type` is `LOAN_OFFSET`,
    whose taxable amount follows the offset variant described in §3.7, and whose
    `event_date` is `terminated_on`."

    Design: Difficulty/transitive_cascade/termination_offset_cascade_tax_events
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    set_clock("2026-08-15T00:00:00Z")
    validate_success(
        api.patch_participant(
            participant["id"],
            {
                "employment_status": "TERMINATED",
                "terminated_on": "2026-08-15T00:00:00Z",
            },
            ADMIN,
        ),
        200,
    )
    loan_after = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_after["lifecycle_status"] == "OFFSET"

    tax_events, _ = validate_paginated(
        api.list_participant_tax_events(participant["id"], ADMIN)
    )
    assert len(tax_events) == 1
    ev = tax_events[0]
    assert ev["source_type"] == "LOAN_OFFSET"
    # Offset cutoff = terminated_on 2026-08-15 -> 3 unpaid due interest portions
    # (installments due 06-01, 07-01, 08-01): 4,167 + 3,827 + 3,487 = 11,481
    assert ev["taxable_amount_cents"] == 1_011_481
    assert ev["tax_year"] == 2026


def test_termination_offset_cascade_updates_participant_ytd_lock_election(api):
    """PRD §3.2: "each created tax event adds its `taxable_amount_cents` into the
    participant's `ytd_taxable_distributions_cents` and sets
    `loan_eligibility_locked_until` to the later of its existing value and
    `terminated_on` plus twelve calendar months. The participant's contribution
    election, if `ACTIVE` or `SUSPENDED`, moves to `TERMINATED`, and
    `contribution_status` follows it to `TERMINATED`."

    Design: Difficulty/transitive_cascade/termination_offset_cascade_tax_events
    """
    plan, participant = setup_plan_and_participant(vested_balance_cents=10_000_000)
    # Create an ACTIVE election first
    from test_helpers import create_contribution_election_payload

    validate_success(
        api.put_contribution_election(
            participant["id"],
            create_contribution_election_payload(deferral_pct=0.1),
            make_participant_headers(participant["id"]),
        ),
        200,
    )
    loan = request_loan(participant, principal_amount_cents=1_000_000, term_months=12)
    approve_loan_fully(loan["id"])
    validate_success(api.disburse_loan(loan["id"], ADMIN), 200)
    set_clock("2026-08-15T00:00:00Z")
    validate_success(
        api.patch_participant(
            participant["id"],
            {
                "employment_status": "TERMINATED",
                "terminated_on": "2026-08-15T00:00:00Z",
            },
            ADMIN,
        ),
        200,
    )
    participant_after = validate_success(
        api.get_participant(participant["id"], ADMIN), 200
    )
    assert participant_after["ytd_taxable_distributions_cents"] == 1_011_481
    assert (
        participant_after["loan_eligibility_locked_until"]
        == "2027-08-15T00:00:00Z"
    )
    assert participant_after["contribution_status"] == "TERMINATED"


# ---------------------------------------------------------------------------
# Corner: deemed_vs_offset_taxable_cutoff_variants
# ---------------------------------------------------------------------------


def test_deemed_vs_offset_taxable_cutoff_variants(api):
    """PRD §3.7: "For the deemed variant the cutoff is `cure_deadline_on` — the
    quarter-end — regardless of the clock date on which the transition fires;
    for the offset variant the cutoff is the event posting date, `terminated_on`.
    Identical loan data and clock therefore produce different taxable amounts
    under the two variants whenever an installment due date falls between the
    two cutoffs."

    Design: Corner/calculations/deemed_vs_offset_taxable_cutoff_variants
    """
    plan = validate_success(api.create_plan(create_plan_payload(), ADMIN), 201)
    p_offset = enroll_participant(plan["id"], vested_balance_cents=10_000_000)
    p_deemed = enroll_participant(plan["id"], vested_balance_cents=10_000_000)
    # Two identical loans
    loan1 = request_loan(p_offset, principal_amount_cents=1_000_000, term_months=12)
    approve_loan_fully(loan1["id"])
    validate_success(api.disburse_loan(loan1["id"], ADMIN), 200)
    loan2 = request_loan(p_deemed, principal_amount_cents=1_000_000, term_months=12)
    approve_loan_fully(loan2["id"])
    validate_success(api.disburse_loan(loan2["id"], ADMIN), 200)
    # Offset path: terminate p_offset at 2026-08-02 (after installments 1,2,3 due)
    set_clock("2026-08-02T00:00:00Z")
    validate_success(
        api.patch_participant(
            p_offset["id"],
            {
                "employment_status": "TERMINATED",
                "terminated_on": "2026-08-02T00:00:00Z",
            },
            ADMIN,
        ),
        200,
    )
    # Deem path: advance past the 2026-09-30 cure deadline
    set_clock("2026-10-01T00:00:00Z")

    ev1, _ = validate_paginated(api.list_participant_tax_events(p_offset["id"], ADMIN))
    ev2, _ = validate_paginated(api.list_participant_tax_events(p_deemed["id"], ADMIN))
    assert ev1[0]["source_type"] == "LOAN_OFFSET"
    assert ev1[0]["taxable_amount_cents"] == 1_011_481
    assert ev1[0]["tax_year"] == 2026
    assert ev2[0]["source_type"] == "LOAN_DEEMED"
    assert ev2[0]["taxable_amount_cents"] == 1_014_625
    assert ev2[0]["tax_year"] == 2026
    assert ev1[0]["taxable_amount_cents"] != ev2[0]["taxable_amount_cents"]


# ---------------------------------------------------------------------------
# Corner: no_deemed_distribution_before_cure_deadline
# ---------------------------------------------------------------------------


def test_no_deemed_distribution_before_cure_deadline(api):
    """PRD §3.7: "When instead the logical clock first advances to a date later
    than `cure_deadline_on` while any `MISSED` installment remains unpaid, the
    deemed distribution fires" — at exactly the deadline the loan is still
    DELINQUENT.

    Design: Corner/cross_cutting_layers/no_deemed_distribution_before_cure_deadline
    """
    _, participant, loan = setup_disbursed_loan(
        principal_amount_cents=1_000_000, term_months=12,
        vested_balance_cents=10_000_000,
    )
    set_clock("2026-06-02T00:00:00Z")
    # At exactly the cure deadline 2026-09-30 — no deem yet
    set_clock("2026-09-30T00:00:00Z")
    loan_now = validate_success(api.get_loan(loan["id"], ADMIN), 200)
    assert loan_now["delinquency_status"] == "DELINQUENT"
    events, meta = validate_paginated(
        api.list_participant_tax_events(participant["id"], ADMIN)
    )
    assert meta["total_count"] == 0
