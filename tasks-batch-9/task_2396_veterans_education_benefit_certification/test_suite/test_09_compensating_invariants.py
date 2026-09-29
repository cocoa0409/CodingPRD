"""Paired debits and credits that must cancel out to the cent and to the day.

A withdrawal effective on the first class day must hand back every entitlement day
the certification charged, and an award reversal must hand back exactly the school
share the award debited, leaving both ledgers where they started.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    create_agreement,
    create_award,
    read_agreement,
    read_certification,
    read_student,
    set_clock_to,
)

FIRST_CLASS_DAY = "2026-08-24"
WITHDRAWAL_REPORTED_DATE = "2026-09-05"
EXPECTED_SCHOOL_SHARE_CENTS = 80000
EXPECTED_POOL_AFTER_AWARD_CENTS = 920000


# ─── The entitlement ledger after a day-zero withdrawal ───────────────
def _withdrawn_on_the_first_class_day(api, baseline):
    """Certify the term, disburse nothing, then withdraw effective on day one."""
    scenario = build_certified_certification(api, baseline)
    set_clock_to(api, WITHDRAWAL_REPORTED_DATE)

    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id,
                FIRST_CLASS_DAY,
                mitigating_circumstances_flag=False,
            ),
            baseline.sco_headers,
        )
    )
    reconciled = get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    return scenario, change_report, reconciled


def test_a_withdrawal_on_the_first_class_day_zeroes_the_covered_tuition(api, baseline):
    """Zero attended days prorate the assessed tuition down to nothing.

    PRD: "For a `COMPLETE_WITHDRAWAL` with `mitigating_circumstances_flag` false,
    tuition is prorated to attendance: count the whole days from
    `term_start_certified` to `effective_date` with the effective date itself
    **excluded**, then set `net_covered_cents` to the as-certified covered amount
    multiplied by that attended-day count, divided by the as-certified
    `certified_days`, rounded half up."

    Design: Difficulty/compensating_invariant/withdrawal_before_first_class_day_restores_entitlement_ledger_exactly
    """
    scenario, _report, _reconciled = _withdrawn_on_the_first_class_day(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_TERMINATED,
            "amount_basis": c.AMOUNT_BASIS_AS_RECONCILED,
            "certified_days": c.CANONICAL_CERTIFIED_DAYS,
            "net_covered_cents": 0,
            "va_tuition_cents": 0,
            "cap_charged_cents": 0,
            "yr_gap_cents": 0,
            "mha_term_total_cents": 0,
        },
    )


def test_the_entitlement_charge_falls_to_zero_on_both_sides_of_the_change(
    api, baseline
):
    """Neither the pre-change side nor the post-change side has a single day in it.

    PRD: "The end of the period after the change is the day before
    `effective_date` for a `COMPLETE_WITHDRAWAL`, `new_term_end_certified` for a
    `TERM_DATE_CHANGE`, and `term_end_certified` for a `CREDIT_HOUR_REDUCTION`;
    the days after the change are the whole days from `effective_date` to that
    end, plus one, floored at 0."

    Design: Difficulty/compensating_invariant/withdrawal_before_first_class_day_restores_entitlement_ledger_exactly
    """
    scenario, _report, _reconciled = _withdrawn_on_the_first_class_day(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_whole_days(certification, "entitlement_days_charged")
    assert certification["entitlement_days_charged"] == 0


def test_the_entitlement_ledger_returns_to_the_granted_total_exactly(api, baseline):
    """The 110 days the certification debited are credited back in full.

    PRD: "First, a student's `entitlement_days_remaining` starts equal to
    `entitlement_days_granted`, which is never mutated after creation; it is
    debited by the entitlement days a certification charges and credited back by
    exactly the difference when reconciliation revises that charge, so that the
    remaining figure always equals the granted figure minus the sum of entitlement
    currently charged."

    Design: Difficulty/compensating_invariant/withdrawal_before_first_class_day_restores_entitlement_ledger_exactly
    """
    scenario, _report, _reconciled = _withdrawn_on_the_first_class_day(api, baseline)

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {
            "entitlement_days_granted": c.ENTITLEMENT_DAYS_GRANTED,
            "entitlement_days_remaining": c.ENTITLEMENT_DAYS_GRANTED,
        },
    )
    a.assert_entitlement_ledger_balances(student, 0)


def test_no_debt_is_raised_when_nothing_was_ever_disbursed(api, baseline):
    """Both overpayment components floor at zero, so there is no debt row to create.

    PRD: "When `principal_cents` is 0 no debt row is created at all."

    Design: Difficulty/compensating_invariant/withdrawal_before_first_class_day_restores_entitlement_ledger_exactly
    """
    scenario, change_report, reconciled = _withdrawn_on_the_first_class_day(
        api, baseline
    )

    assert reconciled["status"] == c.CHANGE_REPORT_STATUS_RECONCILED
    debts = get_success_data(
        api.list_benefit_debts(
            baseline.sup_headers, {"change_report_id": change_report["id"]}
        )
    )
    assert debts == [], f"No debt may be raised for a zero principal, got {debts}"

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["open_debt_principal_cents"] == 0


# ─── The agreement pool ledger across the award lifecycle ─────────────
def _award_on_a_certified_term(api, baseline):
    """One provisional award drawing half of a 160000-cent gap from the pool."""
    scenario = build_certified_certification(api, baseline)
    agreement_id, agreement_version = create_agreement(api, baseline.sup_headers)
    award = create_award(
        api,
        baseline.sup_headers,
        scenario.certification_id,
        agreement_id,
        agreement_version,
    )
    return scenario, agreement_id, award


def test_creating_the_award_debits_the_pool_by_exactly_the_school_share(api, baseline):
    """Half of the 160000-cent gap leaves the pool and one participant is booked.

    PRD: "Award creation debits the agreement: `pool_remaining_cents` falls by
    `school_share_cents`, `participant_count` rises by one, and the agreement's
    `version` increments by one."

    Design: Difficulty/compensating_invariant/yellow_ribbon_award_reversal_restores_pool_and_participant_count_exactly
    """
    _scenario, agreement_id, award = _award_on_a_certified_term(api, baseline)

    a.assert_fields(
        award,
        {
            "status": c.AWARD_STATUS_PROVISIONAL,
            "yr_gap_basis_cents": 160000,
            "school_share_cents": EXPECTED_SCHOOL_SHARE_CENTS,
            "va_match_cents": EXPECTED_SCHOOL_SHARE_CENTS,
            "pool_remaining_before_cents": c.YR_ANNUAL_POOL_CENTS,
        },
    )
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "pool_remaining_cents": EXPECTED_POOL_AFTER_AWARD_CENTS,
            "participant_count": 1,
        },
    )
    a.assert_pool_ledger_balances(agreement, EXPECTED_SCHOOL_SHARE_CENTS)


def test_finalizing_the_award_moves_no_money_at_all(api, baseline):
    """The pool and the participant count sit exactly where the award left them.

    PRD: "Finalization moves no money: the agreement's `pool_remaining_cents` and
    `participant_count` are unchanged, because both `PROVISIONAL` and `FINAL`
    awards are already counted as committed."

    Design: Difficulty/compensating_invariant/yellow_ribbon_award_reversal_restores_pool_and_participant_count_exactly
    """
    _scenario, agreement_id, award = _award_on_a_certified_term(api, baseline)

    finalized = get_success_data(
        api.finalize_yellow_ribbon_award(award["id"], {}, baseline.sup_headers)
    )
    a.assert_fields(
        finalized,
        {
            "status": c.AWARD_STATUS_FINAL,
            "school_share_cents": EXPECTED_SCHOOL_SHARE_CENTS,
            "reversal_reason": None,
        },
    )
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "pool_remaining_cents": EXPECTED_POOL_AFTER_AWARD_CENTS,
            "participant_count": 1,
        },
    )
    a.assert_pool_ledger_balances(agreement, EXPECTED_SCHOOL_SHARE_CENTS)


def test_reversing_a_final_award_restores_the_pool_and_the_participant_count(
    api, baseline
):
    """The credit is exactly the debit, and the reversed award keeps its amounts.

    PRD: "Reversal moves the award to `REVERSED`, which is terminal, stores the
    reason, credits the agreement's `pool_remaining_cents` back by exactly the
    award's `school_share_cents`, decrements `participant_count` by one,
    increments the agreement's `version`, and appends an audit entry with
    `event_type` `AWARD_REVERSED` against the certification the award was made
    for."

    Design: Difficulty/compensating_invariant/yellow_ribbon_award_reversal_restores_pool_and_participant_count_exactly
    """
    _scenario, agreement_id, award = _award_on_a_certified_term(api, baseline)
    get_success_data(
        api.finalize_yellow_ribbon_award(award["id"], {}, baseline.sup_headers)
    )

    reversed_award = get_success_data(
        api.reverse_yellow_ribbon_award(
            award["id"], f.reverse_award_payload(), baseline.sup_headers
        )
    )
    a.assert_fields(
        reversed_award,
        {
            "status": c.AWARD_STATUS_REVERSED,
            "reversal_reason": "Student rescinded Yellow Ribbon participation",
            "school_share_cents": EXPECTED_SCHOOL_SHARE_CENTS,
            "va_match_cents": EXPECTED_SCHOOL_SHARE_CENTS,
        },
    )
    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {
            "status": c.AGREEMENT_STATUS_ACTIVE,
            "pool_remaining_cents": c.YR_ANNUAL_POOL_CENTS,
            "participant_count": 0,
        },
    )


def test_the_restored_pool_carries_no_committed_school_share(api, baseline):
    """With no live award the ledger reads back its untouched annual pool.

    PRD: "Second, an agreement's `pool_remaining_cents` starts equal to
    `annual_pool_cents`, which is never mutated after creation; it is debited by
    an award's school share when the award is created and credited by exactly that
    same school share when the award is reversed, while `participant_count` counts
    the agreement's awards that are provisional or final and moves by one in step
    with each of those events."

    Design: Difficulty/compensating_invariant/yellow_ribbon_award_reversal_restores_pool_and_participant_count_exactly
    """
    scenario, agreement_id, award = _award_on_a_certified_term(api, baseline)
    get_success_data(
        api.reverse_yellow_ribbon_award(
            award["id"], f.reverse_award_payload(), baseline.sup_headers
        )
    )

    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    assert agreement["annual_pool_cents"] == c.YR_ANNUAL_POOL_CENTS
    a.assert_pool_ledger_balances(agreement, 0)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {"status": c.CERT_STATUS_CERTIFIED, "yr_gap_cents": 160000},
    )
