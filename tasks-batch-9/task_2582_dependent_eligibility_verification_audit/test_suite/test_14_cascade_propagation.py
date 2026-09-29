"""The two deep cascades: escalation forwards and an appeal grant backwards.

Each link in these chains is caused by the previous link rather than directly by
the request, so every test walks the whole chain the specification describes.
"""
from __future__ import annotations

from test_helpers.assertions import assert_instant_equals, assert_priority_score
from test_helpers.fixtures import (
    ANNOUNCE_INSTANT,
    APPEAL_INSTANT,
    ESCALATION_INSTANT,
    ORIGIN_INSTANT,
    recovery_wave,
)
from test_helpers.types import Ctx

PAYMENT_INSTANT = "2026-11-03T00:00:00Z"


def _two_silent_households(b) -> Ctx:
    """One spouse case and one domestic-partner case, both notified and silent."""
    b.set_clock(ORIGIN_INSTANT)
    employee_one = b.employee()
    employee_two = b.employee()
    spouse = b.dependent(employee_one["id"], "SPOUSE")
    partner = b.dependent(employee_two["id"], "DOMESTIC_PARTNER")

    program = b.program()
    b.doc_rules(program["id"], ("SPOUSE", "DOMESTIC_PARTNER"))
    b.scope(program["id"], "FULL_CENSUS")

    b.set_clock(ANNOUNCE_INSTANT)
    b.communicate(program["id"])
    cases = b.cases(program["id"])
    return Ctx(
        program=b.read_program(program["id"]),
        spouse_case=next(
            row for row in cases if row["employee_id"] == employee_one["id"]
        ),
        partner_case=next(
            row for row in cases if row["employee_id"] == employee_two["id"]
        ),
        spouse=spouse,
        partner=partner,
    )


def test_the_escalation_sweep_cascades_through_case_dependent_and_notice(b):
    """One sweep closes amnesty, escalates both cases and issues both notices.

    PRD: "Because a case became `NON_RESPONSIVE`, each member of its
    `in_scope_dependent_ids` still sitting at `PENDING_VERIFICATION`, taken in
    ascending dependent `created_at`, moves `PENDING_VERIFICATION →
    TERMINATION_PENDING`."

    Design: Difficulty/transitive_cascade/escalation_sweep_cascades_program_case_dependent_notice_counters
    """
    ctx = _two_silent_households(b)
    b.set_clock(ESCALATION_INSTANT)

    program = b.sweep(ctx.program["id"])

    assert program["status"] == "ESCALATION"
    assert program["sweep_epoch"] == 1

    spouse_case = b.read_case(ctx.spouse_case["id"])
    partner_case = b.read_case(ctx.partner_case["id"])
    assert spouse_case["status"] == "ESCALATED"
    assert partner_case["status"] == "ESCALATED"
    assert_instant_equals(spouse_case["non_responsive_at"], ESCALATION_INSTANT)
    assert_instant_equals(spouse_case["escalated_at"], ESCALATION_INSTANT)

    assert b.read_dependent(ctx.spouse["id"])["coverage_status"] == "TERMINATION_PENDING"
    assert b.read_dependent(ctx.partner["id"])["coverage_status"] == "TERMINATION_PENDING"

    notice = b.notice_for(ctx.spouse["id"])
    assert notice["status"] == "ISSUED"
    assert notice["origin"] == "AUDIT_ESCALATION"
    assert notice["case_id"] == ctx.spouse_case["id"]
    assert_instant_equals(notice["issued_at"], ESCALATION_INSTANT)
    assert notice["effective_date"] == "2026-10-31"
    assert notice["grace_days_applied"] == 14
    assert notice["continuation_monthly_premium_cents"] == 0
    assert_instant_equals(
        notice["continuation_election_deadline"], "2026-12-16T00:00:00Z"
    )

    _rows, meta = b.communications(
        ctx.spouse_case["id"], kind="TERMINATION_NOTICE"
    )
    assert meta["total_count"] == 1


def test_notice_batch_sequence_follows_descending_priority_score(b):
    """The sensitive-relationship case scores 80, is processed first and takes batch one.

    PRD: "one `TerminationNotice` is created for it in `ISSUED` with `origin`
    `AUDIT_ESCALATION`, `case_id` naming the owning case, `issued_at` at the
    current clock instant, `grace_days_applied` recording the fourteen-day grace
    period, an `effective_date` computed as described in §3.7, a
    `continuation_election_deadline` sixty days past issuance,
    `continuation_monthly_premium_cents` at zero, and a `batch_sequence_no`
    assigned one-based within this sweep batch in exactly the processing order
    just described — cases by descending priority then ascending creation,
    dependents within a case by ascending creation."

    Design: Difficulty/transitive_cascade/escalation_sweep_cascades_program_case_dependent_notice_counters
    """
    ctx = _two_silent_households(b)
    b.set_clock(ESCALATION_INSTANT)
    b.sweep(ctx.program["id"])

    spouse_case = b.read_case(ctx.spouse_case["id"])
    partner_case = b.read_case(ctx.partner_case["id"])
    assert spouse_case["priority_score"] == 55
    assert partner_case["priority_score"] == 80
    assert_priority_score(
        spouse_case,
        unverified=1,
        in_scope=1,
        sensitive=False,
        reminders=0,
        max_reminders=3,
        silent=True,
    )
    assert_priority_score(
        partner_case,
        unverified=1,
        in_scope=1,
        sensitive=True,
        reminders=0,
        max_reminders=3,
        silent=True,
    )

    assert b.notice_for(ctx.partner["id"])["batch_sequence_no"] == 1
    assert b.notice_for(ctx.spouse["id"])["batch_sequence_no"] == 2


def test_the_escalation_cascade_recomputes_every_affected_program_counter(b):
    """The last link of the chain is the program's own counter recompute.

    PRD: "Finally, `non_responsive_case_count` — the number of cases in
    `NON_RESPONSIVE` or `ESCALATED` — along with `pending_dependent_count`,
    `termination_pending_count`, and `provisional_annual_savings_cents` are all
    recomputed on the program."

    Design: Difficulty/transitive_cascade/escalation_sweep_cascades_program_case_dependent_notice_counters
    """
    ctx = _two_silent_households(b)
    b.set_clock(ESCALATION_INSTANT)

    program = b.sweep(ctx.program["id"])

    assert program["non_responsive_case_count"] == 2
    assert program["termination_pending_count"] == 2
    assert program["pending_dependent_count"] == 0
    assert program["in_scope_dependent_count"] == 2
    # Two 49713-cent dependents annualised at twelve months apiece.
    assert program["provisional_annual_savings_cents"] == 1193112


RECOVERABLE_CLAIMS = (
    {"service_date": "2026-09-20", "paid_cents": 240000},
    {"service_date": "2026-09-25", "paid_cents": 250000},
)


def _partially_recovered_dependent_with_an_appeal(b) -> Ctx:
    """A finalised termination that has already paid 100000 against its demand."""
    ctx = recovery_wave(b, claims=list(RECOVERABLE_CLAIMS), issue=True)
    b.set_clock(PAYMENT_INSTANT)
    ctx.recovery = b.payment(ctx.recovery["id"], 100000, "2026-11-03")
    assert ctx.recovery["status"] == "PARTIALLY_RECOVERED"

    b.set_clock(APPEAL_INSTANT)
    ctx.appeal = b.appeal(
        ctx.case["id"], ctx.dep["id"], ctx.employee["id"], "ADMINISTRATIVE_ERROR"
    )
    ctx.appeal = b.assign_appeal(ctx.appeal["id"])
    return ctx


def test_a_granted_appeal_reinstates_a_terminated_dependent_and_rescinds_its_final_notice(b):
    """Termination had already completed, so restoration takes the reinstatement branch.

    PRD: "When the dependent has already reached `TERMINATED` and its notice has
    already reached `FINAL`, the dependent moves `TERMINATED → REINSTATED` with
    `reinstated_at` set to the current clock instant and `coverage_end_date`
    cleared back to null."

    Design: Difficulty/transitive_cascade/appeal_grant_cascade_unwinds_notice_recovery_and_program_ledger
    """
    ctx = _partially_recovered_dependent_with_an_appeal(b)
    assert b.read_notice(ctx.notice["id"])["status"] == "FINAL"

    granted = b.decide_appeal(ctx.appeal["id"], "GRANT")
    assert granted["status"] == "GRANTED"

    dependent = b.read_dependent(ctx.dep["id"])
    assert dependent["coverage_status"] == "REINSTATED"
    assert_instant_equals(dependent["reinstated_at"], APPEAL_INSTANT)
    assert dependent["coverage_end_date"] is None

    notice = b.read_notice(ctx.notice["id"])
    assert notice["status"] == "RESCINDED"
    assert notice["rescission_reason"] == "APPEAL_GRANTED"
    assert_instant_equals(notice["rescinded_at"], APPEAL_INSTANT)


def test_a_granted_appeal_voids_the_collecting_recovery_and_owes_the_money_back(b):
    """Money collected from an eligible dependent turns into a refund obligation.

    PRD: "Fourth, because the notice was rescinded, every `ClaimRecovery` of that
    dependent whose `status` is `OPEN`, `DEMAND_ISSUED`, or `PARTIALLY_RECOVERED`
    moves to `VOIDED`, and each such row's `refund_due_cents` is set equal to its
    `recovered_cents` — money already collected from a subscriber whose dependent
    turns out to have been eligible is owed straight back."

    Design: Difficulty/transitive_cascade/appeal_grant_cascade_unwinds_notice_recovery_and_program_ledger
    """
    ctx = _partially_recovered_dependent_with_an_appeal(b)
    before = b.read_program(ctx.program["id"])
    assert before["recovery_ledger_cents"] == 514500
    assert before["recovered_total_cents"] == 100000
    assert before["refund_due_total_cents"] == 0

    b.decide_appeal(ctx.appeal["id"], "GRANT")

    recovery = b.read_recovery(ctx.recovery["id"])
    assert recovery["status"] == "VOIDED"
    assert recovery["recovered_cents"] == 100000
    assert recovery["refund_due_cents"] == 100000

    program = b.read_program(ctx.program["id"])
    assert program["recovery_ledger_cents"] == 0
    assert program["recovered_total_cents"] == 0
    assert program["refund_due_total_cents"] == 100000


def test_the_restored_dependent_was_the_last_unresolved_one_so_the_case_completes(b):
    """With nothing left unresolved the re-opened case lands on COMPLETE.

    PRD: "This is the audit's one genuine cycle: an escalated case can return to
    an in-progress state and be worked again."

    Design: Difficulty/transitive_cascade/appeal_grant_cascade_unwinds_notice_recovery_and_program_ledger
    """
    ctx = _partially_recovered_dependent_with_an_appeal(b)
    assert b.read_case(ctx.case["id"])["status"] == "ESCALATED"

    b.decide_appeal(ctx.appeal["id"], "GRANT")

    case = b.read_case(ctx.case["id"])
    assert case["status"] == "COMPLETE"
    assert_instant_equals(case["completed_at"], APPEAL_INSTANT)

    program = b.read_program(ctx.program["id"])
    assert program["terminated_dependent_count"] == 0
    assert program["verified_dependent_count"] == 1
    assert program["audited_annual_savings_cents"] == 0
