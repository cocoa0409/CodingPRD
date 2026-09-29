"""The pinned arithmetic of a dependent eligibility verification audit.

The effective date of a notice raised by a lapsed point-of-enrollment add, the
ceiling on the triage score, the narrowed in-scope set of a new-dependent run,
the per-line floor of an equitable claims recovery, the administrative fee tier
boundary, and the savings figures the deferred-action checkpoint recomputes on
its own without anyone asking for a measurement.
"""
from __future__ import annotations

import pytest

from test_helpers.assertions import (
    assert_case,
    assert_demand_pricing,
    assert_dependent,
    assert_instant_equals,
    assert_notice,
    assert_priority_score,
    assert_program,
    assert_recovery,
    counters,
)
from test_helpers.constants import MONTHLY_COST_CENTS
from test_helpers.fixtures import (
    FINALIZE_INSTANT,
    announced_wave,
    escalated_wave,
    finalized_wave,
    poe_wave,
)

# The point-of-enrollment thread: a child enrolled on 5 September under a rule
# granting thirty days of grace has until 5 October to be documented.
_POE_ENROLL_INSTANT = "2026-09-05T00:00:00Z"
_POE_DEADLINE_INSTANT = "2026-10-05T00:00:00Z"
_BEFORE_LAPSE_INSTANT = "2026-10-04T00:00:00Z"
_LAPSE_SWEEP_INSTANT = "2026-10-06T00:00:00Z"
_POE_EFFECTIVE_DATE = "2026-10-31"
_POE_ELECTION_DEADLINE_INSTANT = "2026-12-05T00:00:00Z"

# Three reminders exactly the configured seven whole days apart.
_FIRST_REMINDER_INSTANT = "2026-09-08T00:00:00Z"
_SECOND_REMINDER_INSTANT = "2026-09-15T00:00:00Z"
_THIRD_REMINDER_INSTANT = "2026-09-22T00:00:00Z"

# The new-dependent thread: a child added on 2 September, a cutoff of 1 September.
_NEW_DEPENDENT_ENROLL_INSTANT = "2026-09-02T00:00:00Z"
_NEW_DEPENDENT_CUTOFF = "2026-09-01"

_COVERAGE_END_DATE = "2026-10-31"


def _lapse_notices(b):
    """Every point-of-enrollment lapse notice, read through the origin filter."""
    return b.notices(origin="POE_LAPSE")


def test_a_lapsed_point_of_enrollment_add_is_dated_from_its_own_grace_deadline(b):
    """PRD §3.7: "For a notice whose `origin` is `POE_LAPSE`, the computation is
    simpler and carries no floor at all: the anchor is the calendar date of the
    dependent's `poe_deadline_at` advanced by the same fourteen whole days."
    ... "In both branches, `grace_days_applied` records the fourteen days that
    were used, and the notice's `effective_date` is the last calendar day of the
    month containing the anchor"

    Design: Corner/calculations/corner_poe_lapse_notice_uses_the_poe_branch_of_the_effective_date_formula
    """
    ctx = poe_wave(b, enroll_at=_POE_ENROLL_INSTANT)
    enrolled = b.read_dependent(ctx.poe_dependent["id"])
    assert_dependent(
        enrolled,
        coverage_status="PENDING_VERIFICATION",
        poe_program_id=ctx.program["id"],
        documentation_complete=False,
    )
    assert_instant_equals(enrolled["poe_deadline_at"], _POE_DEADLINE_INSTANT)

    b.set_clock(_LAPSE_SWEEP_INSTANT)
    b.sweep(ctx.program["id"])

    lapsed = _lapse_notices(b)
    assert len(lapsed) == 1, lapsed
    notice = lapsed[0]
    assert_notice(
        notice,
        dependent_id=ctx.poe_dependent["id"],
        origin="POE_LAPSE",
        status="ISSUED",
        grace_days_applied=14,
        effective_date=_POE_EFFECTIVE_DATE,
        continuation_election_status="NOT_ELECTED",
        continuation_monthly_premium_cents=0,
    )
    assert_instant_equals(notice["issued_at"], _LAPSE_SWEEP_INSTANT)
    assert_instant_equals(
        notice["continuation_election_deadline"], _POE_ELECTION_DEADLINE_INSTANT
    )
    assert_dependent(
        b.read_dependent(ctx.poe_dependent["id"]),
        coverage_status="TERMINATION_PENDING",
        documentation_complete=False,
    )


def test_a_lapse_notice_carries_no_case_and_leaves_the_audit_case_untouched(b):
    """PRD §3.6: "A lapse notice has no case behind it — its `case_id` is null"
    ... "Every dependent whose `poe_program_id` names this program, whose
    `coverage_status` is `PENDING_VERIFICATION`, whose `poe_deadline_at` is at or
    before the current clock instant, whose `documentation_complete` is still
    false, and whose governing point-of-enrollment rule has
    `auto_terminate_on_lapse` true, taken in ascending `created_at`, moves
    `PENDING_VERIFICATION → TERMINATION_PENDING` and receives one
    `TerminationNotice` in `ISSUED` with `origin` `POE_LAPSE`."

    Design: Corner/calculations/corner_poe_lapse_notice_uses_the_poe_branch_of_the_effective_date_formula
    """
    ctx = poe_wave(b, enroll_at=_POE_ENROLL_INSTANT)

    b.set_clock(_BEFORE_LAPSE_INSTANT)
    b.sweep(ctx.program["id"])
    assert _lapse_notices(b) == []
    assert_dependent(
        b.read_dependent(ctx.poe_dependent["id"]),
        coverage_status="PENDING_VERIFICATION",
    )

    b.set_clock(_LAPSE_SWEEP_INSTANT)
    b.sweep(ctx.program["id"])

    notice = _lapse_notices(b)[0]
    assert notice["case_id"] is None, notice
    assert_case(b.read_case(ctx.case["id"]), status="NOTIFIED")


def _chase_a_silent_domestic_partner_case(b):
    """Announce over one domestic-partner household and chase it three times."""
    ctx = announced_wave(b, relationships=("DOMESTIC_PARTNER",))
    for instant in (
        _FIRST_REMINDER_INSTANT,
        _SECOND_REMINDER_INSTANT,
        _THIRD_REMINDER_INSTANT,
    ):
        b.set_clock(instant)
        channel = "MAIL" if instant == _THIRD_REMINDER_INSTANT else "EMAIL"
        ctx.case = b.reminder(ctx.case["id"], channel=channel)
    return ctx


def test_a_fully_chased_sensitive_and_silent_case_scores_the_ceiling_of_one_hundred(b):
    """PRD §3.3: "The four weighted terms are added using real division for the
    two ratios, the sum is rounded half up to a single integer exactly once at
    the end, and only then is a ceiling of 100 applied — so a case that would
    score 104 before capping stores 100."

    Design: Corner/calculations/corner_priority_score_saturates_at_the_declared_ceiling_of_one_hundred
    """
    ctx = _chase_a_silent_domestic_partner_case(b)

    assert_case(
        ctx.case,
        in_scope_dependent_count=1,
        unverified_dependent_count=1,
        proof_submission_count=0,
        reminders_sent_count=3,
        priority_score=100,
    )
    assert_priority_score(
        ctx.case,
        unverified=1,
        in_scope=1,
        sensitive=True,
        reminders=3,
        max_reminders=3,
        silent=True,
    )
    assert_case(b.read_case(ctx.case["id"]), priority_score=100)


def test_each_accepted_reminder_advances_the_case_ledger_and_the_outreach_trail(b):
    """PRD §3.3: "An accepted reminder increments the case's
    `reminders_sent_count`, sets `last_reminder_at` to the current clock instant,
    increments `communication_sequence_no`, and appends one `CommunicationEvent`
    with `kind` `REMINDER` carrying that new sequence number." ... "It then
    recomputes the case's `priority_score`."

    Design: Corner/calculations/corner_priority_score_saturates_at_the_declared_ceiling_of_one_hundred
    """
    ctx = _chase_a_silent_domestic_partner_case(b)

    assert_case(ctx.case, reminders_sent_count=3, communication_sequence_no=4)
    assert_instant_equals(ctx.case["last_reminder_at"], _THIRD_REMINDER_INSTANT)

    reminders, meta = b.communications(ctx.case["id"], kind="REMINDER")
    assert meta["total_count"] == 3, meta
    assert [row["sequence_no"] for row in reminders] == [2, 3, 4], reminders
    assert reminders[2]["channel"] == "MAIL", reminders[2]
    assert reminders[2]["kind"] == "REMINDER", reminders[2]


def _new_dependent_census(b):
    """A long-standing spouse, then a child enrolled after the cutoff date."""
    employee = b.employee()
    spouse = b.dependent(employee["id"], "SPOUSE")
    program = b.program(program_name="PY2026 New Dependent Audit")
    b.doc_rules(program["id"], ("SPOUSE", "CHILD_BIOLOGICAL"))
    b.set_clock(_NEW_DEPENDENT_ENROLL_INSTANT)
    child = b.dependent(employee["id"], "CHILD_BIOLOGICAL")
    return employee, spouse, child, program


def test_a_new_dependent_run_puts_only_the_recently_enrolled_child_in_the_case(b, clock):
    """PRD §3.2: "Under `NEW_DEPENDENT_ONLY` the per-case set is narrowed further
    to only those enrolled dependents whose `enrolled_at` falls on or after
    `new_dependent_since_date`, so an employee can be in scope for their newly
    added stepchild without their spouse of fifteen years being dragged in."

    Design: Corner/calculations/corner_new_dependent_only_scope_narrows_the_case_to_dependents_enrolled_since_the_cutoff
    """
    employee, spouse, child, program = _new_dependent_census(b)

    scoped = b.scope(
        program["id"],
        "NEW_DEPENDENT_ONLY",
        new_dependent_since_date=_NEW_DEPENDENT_CUTOFF,
    )
    assert_program(
        scoped,
        status="SCOPED",
        scope_type="NEW_DEPENDENT_ONLY",
        in_scope_case_count=1,
        in_scope_dependent_count=1,
        pending_dependent_count=1,
    )

    cases = b.cases(program["id"])
    assert len(cases) == 1, cases
    assert_case(
        cases[0],
        employee_id=employee["id"],
        in_scope_dependent_ids=[child["id"]],
        in_scope_dependent_count=1,
        priority_score=55,
    )
    assert spouse["id"] not in cases[0]["in_scope_dependent_ids"]


def test_a_dependent_enrolled_before_the_cutoff_is_left_in_enrolled_coverage(b, clock):
    """PRD §3.2: "Under `NEW_DEPENDENT_ONLY` the per-case set is narrowed further
    to only those enrolled dependents whose `enrolled_at` falls on or after
    `new_dependent_since_date`" ... "On success, every selected dependent moves
    `ENROLLED → PENDING_VERIFICATION`"

    Design: Corner/calculations/corner_new_dependent_only_scope_narrows_the_case_to_dependents_enrolled_since_the_cutoff
    """
    _employee, spouse, child, program = _new_dependent_census(b)

    b.scope(
        program["id"],
        "NEW_DEPENDENT_ONLY",
        new_dependent_since_date=_NEW_DEPENDENT_CUTOFF,
    )

    assert_dependent(b.read_dependent(spouse["id"]), coverage_status="ENROLLED")
    assert_dependent(
        b.read_dependent(child["id"]),
        coverage_status="PENDING_VERIFICATION",
        enrolled_at="2026-09-02",
    )


_EQUITABLE_CLAIMS = (
    {"service_date": "2026-08-20", "paid_cents": 60000, "employee_premium_offset_cents": 0},
    {"service_date": "2026-09-20", "paid_cents": 40000, "employee_premium_offset_cents": 50000},
    {"service_date": "2026-09-25", "paid_cents": 30000, "employee_premium_offset_cents": 0},
)


def test_an_equitable_subtotal_floors_an_over_offset_line_at_zero_not_below(b):
    """PRD §3.9: "Under `EQUITABLE`, the window instead opens at the calendar date
    of the program's `announcement_at`" ... "That per-line floor of zero is
    applied **line by line, before summation**, never to the total."

    Design: Corner/calculations/corner_equitable_recovery_floors_each_line_at_zero_before_summing
    """
    ctx = finalized_wave(b, claims=_EQUITABLE_CLAIMS)

    recovery = b.open_recovery(
        ctx.dep["id"],
        ctx.notice["id"],
        "EQUITABLE",
        ineligibility_onset_date="2026-08-01",
    )
    assert_recovery(
        recovery,
        status="OPEN",
        recovery_variant="EQUITABLE",
        recoverable_subtotal_cents=30000,
    )


def test_a_zero_floored_equitable_demand_carries_no_administrative_fee(b):
    """PRD §3.9: "Step two selects the fee rate **from that subtotal**, never from
    any fee-inclusive figure: a subtotal below 100,000 cents attracts a rate of
    zero, a subtotal from 100,000 cents up to but not including 500,000 cents
    attracts five percent, and a subtotal of 500,000 cents or more attracts eight
    percent." ... "Recording one increases the dependent's
    `paid_claims_total_cents` by the line's `paid_cents`, that field being the
    exact sum of the dependent's paid lines."

    Design: Corner/calculations/corner_equitable_recovery_floors_each_line_at_zero_before_summing
    """
    ctx = finalized_wave(b, claims=_EQUITABLE_CLAIMS)
    recovery = b.open_recovery(
        ctx.dep["id"],
        ctx.notice["id"],
        "EQUITABLE",
        ineligibility_onset_date="2026-08-01",
    )

    issued = b.issue_demand(recovery["id"])

    assert_recovery(issued, status="DEMAND_ISSUED")
    assert_demand_pricing(issued, subtotal_cents=30000)
    assert issued["net_demand_cents"] == 30000, issued
    assert_dependent(
        b.read_dependent(ctx.dep["id"]),
        paid_claims_total_cents=130000,
        coverage_end_date=_COVERAGE_END_DATE,
    )


@pytest.mark.parametrize(
    "paid_cents, expected_pct, expected_fee, expected_net",
    [
        (99999, 0.0, 0, 99999),
        (100000, 0.05, 5000, 105000),
    ],
)
def test_the_administrative_fee_tier_turns_on_a_single_cent_of_subtotal(
    b, paid_cents, expected_pct, expected_fee, expected_net
):
    """PRD §3.9: "Step two selects the fee rate **from that subtotal**, never from
    any fee-inclusive figure: a subtotal below 100,000 cents attracts a rate of
    zero, a subtotal from 100,000 cents up to but not including 500,000 cents
    attracts five percent, and a subtotal of 500,000 cents or more attracts eight
    percent." ... "Step three multiplies the subtotal by that rate and rounds the
    product half up to a whole cent exactly once, storing the result in
    `admin_fee_cents`"

    Design: Corner/calculations/corner_admin_fee_tier_boundary_is_exclusive_below_and_inclusive_at_one_hundred_thousand
    """
    ctx = finalized_wave(
        b, claims=({"service_date": "2026-09-20", "paid_cents": paid_cents},)
    )
    recovery = b.open_recovery(ctx.dep["id"], ctx.notice["id"], "STRICT", "2026-09-01")
    assert_recovery(recovery, recoverable_subtotal_cents=paid_cents)

    issued = b.issue_demand(recovery["id"])

    assert_recovery(
        issued,
        status="DEMAND_ISSUED",
        recoverable_subtotal_cents=paid_cents,
        admin_fee_cents=expected_fee,
        waiver_credit_cents=0,
        net_demand_cents=expected_net,
    )
    assert issued["admin_fee_pct"] == pytest.approx(expected_pct), issued
    assert_demand_pricing(issued, subtotal_cents=paid_cents)
    assert_instant_equals(issued["demand_issued_at"], FINALIZE_INSTANT)


def test_two_demands_astride_the_fee_tier_sum_into_the_program_recovery_ledger(b):
    """PRD §3.9: "`recovery_ledger_cents` is the sum of `net_demand_cents` across
    those recoveries whose `status` is `DEMAND_ISSUED`, `PARTIALLY_RECOVERED`, or
    `RECOVERED`" ... "The row then moves `OPEN → DEMAND_ISSUED` with
    `demand_issued_at` set to the current clock instant, and the program's
    `recovery_ledger_cents` is recomputed now that this row's `net_demand_cents`
    counts."

    Design: Corner/calculations/corner_admin_fee_tier_boundary_is_exclusive_below_and_inclusive_at_one_hundred_thousand
    """
    ctx = finalized_wave(
        b,
        relationships=("SPOUSE", "CHILD_BIOLOGICAL"),
        claims=(
            {"dependent_index": 0, "service_date": "2026-09-20", "paid_cents": 99999},
            {"dependent_index": 1, "service_date": "2026-09-20", "paid_cents": 100000},
        ),
    )

    for dependent, subtotal in ((ctx.dep1, 99999), (ctx.dep2, 100000)):
        notice = ctx.notices[dependent["id"]]
        recovery = b.open_recovery(dependent["id"], notice["id"], "STRICT", "2026-09-01")
        issued = b.issue_demand(recovery["id"])
        assert_demand_pricing(issued, subtotal_cents=subtotal)

    program = b.read_program(ctx.program["id"])
    assert_program(
        program,
        recovery_ledger_cents=204999,
        recovered_total_cents=0,
        refund_due_total_cents=0,
    )


_SPOUSE_MONTHLY_COST = MONTHLY_COST_CENTS["SPOUSE"]
_PROVISIONAL_SAVINGS = _SPOUSE_MONTHLY_COST * 12
_AUDITED_SAVINGS = _SPOUSE_MONTHLY_COST * 2


def test_a_dependent_still_under_notice_counts_provisionally_but_not_as_audited(b):
    """PRD §3.9: "The `PROVISIONAL` variant includes every in-scope dependent whose
    `coverage_status` is `AMNESTY_REMOVED`, `TERMINATION_PENDING`, or
    `TERMINATED`, and credits each one a full twelve months of its monthly cost
    regardless of when coverage actually ended" ... "The `AUDITED` variant
    excludes `TERMINATION_PENDING` dependents entirely — nothing has actually been
    saved from a dependent still under notice — and prorates each remaining
    dependent by twelve minus the calendar month number of that dependent's
    `coverage_end_date`, so a dependent whose coverage ended on the last day of
    September, month nine, contributes three months of its monthly cost."

    Design: Corner/calculations/corner_notice_finalization_recomputes_savings_under_the_audited_variant_without_an_explicit_call
    """
    ctx = escalated_wave(b)

    assert_dependent(
        b.read_dependent(ctx.dep["id"]), coverage_status="TERMINATION_PENDING"
    )
    assert_program(
        ctx.program,
        provisional_annual_savings_cents=_PROVISIONAL_SAVINGS,
        audited_annual_savings_cents=0,
        termination_pending_count=1,
        terminated_dependent_count=0,
    )
    assert counters(ctx.program, "provisional_annual_savings_cents") == {
        "provisional_annual_savings_cents": 596556
    }


def test_the_finalizing_checkpoint_recomputes_audited_savings_with_no_measurement_call(b):
    """PRD §3.9: "The `AUDITED` variant excludes `TERMINATION_PENDING` dependents
    entirely — nothing has actually been saved from a dependent still under notice
    — and prorates each remaining dependent by twelve minus the calendar month
    number of that dependent's `coverage_end_date`, so a dependent whose coverage
    ended on the last day of September, month nine, contributes three months of
    its monthly cost." ... "it is the figure recomputed automatically whenever a
    notice finalises, an appeal is granted, or the program closes"

    Design: Corner/calculations/corner_notice_finalization_recomputes_savings_under_the_audited_variant_without_an_explicit_call
    """
    ctx = escalated_wave(b)

    b.set_clock(FINALIZE_INSTANT)
    swept = b.sweep(ctx.program["id"])

    assert_program(
        swept,
        status="ESCALATION",
        sweep_epoch=3,
        audited_annual_savings_cents=_AUDITED_SAVINGS,
        provisional_annual_savings_cents=_PROVISIONAL_SAVINGS,
        terminated_dependent_count=1,
        termination_pending_count=0,
    )
    assert swept["audited_annual_savings_cents"] == 99426, swept
    assert_dependent(
        b.read_dependent(ctx.dep["id"]),
        coverage_status="TERMINATED",
        coverage_end_date=_COVERAGE_END_DATE,
    )
