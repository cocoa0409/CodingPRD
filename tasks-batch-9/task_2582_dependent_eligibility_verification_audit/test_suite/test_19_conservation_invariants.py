"""Quantities that must balance before and after a disruptive event.

The first is a headcount partition over the in-scope population; the second is
collected cash, which the appeal cascade may move between books but may neither
create nor destroy.
"""
from __future__ import annotations

from test_helpers.assertions import assert_counter_partition, counters
from test_helpers.fixtures import (
    ESCALATION_INSTANT,
    FINALIZE_INSTANT,
    RESPONSE_WINDOW_INSTANT,
    REVIEW_INSTANT,
    announced_wave,
    recovery_wave,
)
from test_helpers.test_users import REVIEWER

THREE_DEPENDENTS = ("SPOUSE", "CHILD_BIOLOGICAL", "STEPCHILD")
AMNESTY_INSTANT = "2026-09-10T00:00:00Z"
# The child's coverage ends 2026-09-30, booking three months at 30500; the
# stepchild's ends 2026-10-31, booking two.
AUDITED_SAVINGS_CENTS = 152500
# Both non-verified dependents credited a full twelve months at 30500.
PROVISIONAL_SAVINGS_CENTS = 732000
PARTITION_FIELDS = (
    "in_scope_dependent_count",
    "pending_dependent_count",
    "verified_dependent_count",
    "amnesty_removed_count",
    "termination_pending_count",
    "terminated_dependent_count",
)


def _household_with_one_removal_and_one_verification(b):
    """Three in-scope dependents: one removed under amnesty, one verified, one silent."""
    ctx = announced_wave(b, relationships=THREE_DEPENDENTS)

    b.set_clock(AMNESTY_INSTANT)
    b.amnesty_removal(ctx.dep2["id"], ctx.case["id"], ctx.employee["id"])

    b.set_clock(RESPONSE_WINDOW_INSTANT)
    b.sweep(ctx.program["id"])

    b.set_clock(REVIEW_INSTANT)
    submission = b.submit_proof(
        ctx.case["id"], ctx.dep1["id"], ctx.employee["id"], "MARRIAGE_CERTIFICATE"
    )
    b.accept_proof(submission["id"])
    ctx.program = b.read_program(ctx.program["id"])
    return ctx


def test_the_headcount_partition_holds_with_three_dependents_in_three_buckets(b):
    """One pending, one verified, one amnesty-removed still sums to three.

    PRD: "Five counters partition the in-scope dependent population by
    `coverage_status`: `pending_dependent_count` counts those in
    `PENDING_VERIFICATION`, `amnesty_removed_count` those in `AMNESTY_REMOVED`,
    `termination_pending_count` those in `TERMINATION_PENDING`,
    `terminated_dependent_count` those in `TERMINATED`, and
    `verified_dependent_count` those in **either** `VERIFIED` **or**
    `REINSTATED`"

    Design: Difficulty/compensating_invariant/in_scope_dependent_headcount_conserved_across_amnesty_verification_and_termination
    """
    ctx = _household_with_one_removal_and_one_verification(b)

    program = ctx.program
    assert counters(program, *PARTITION_FIELDS) == {
        "in_scope_dependent_count": 3,
        "pending_dependent_count": 1,
        "verified_dependent_count": 1,
        "amnesty_removed_count": 1,
        "termination_pending_count": 0,
        "terminated_dependent_count": 0,
    }
    assert_counter_partition(program)


def test_escalation_shifts_the_last_pending_dependent_without_changing_the_total(b):
    """The pending bucket empties into the termination-pending bucket.

    PRD: "Because a case became `NON_RESPONSIVE`, each member of its
    `in_scope_dependent_ids` still sitting at `PENDING_VERIFICATION`, taken in
    ascending dependent `created_at`, moves `PENDING_VERIFICATION →
    TERMINATION_PENDING`."

    Design: Difficulty/compensating_invariant/in_scope_dependent_headcount_conserved_across_amnesty_verification_and_termination
    """
    ctx = _household_with_one_removal_and_one_verification(b)

    b.set_clock(ESCALATION_INSTANT)
    b.sweep(ctx.program["id"])

    program = b.read_program(ctx.program["id"])
    assert counters(program, *PARTITION_FIELDS) == {
        "in_scope_dependent_count": 3,
        "pending_dependent_count": 0,
        "verified_dependent_count": 1,
        "amnesty_removed_count": 1,
        "termination_pending_count": 1,
        "terminated_dependent_count": 0,
    }
    assert_counter_partition(program)

    case = b.read_case(ctx.case["id"])
    assert case["status"] == "ESCALATED"
    assert case["unverified_dependent_count"] == 1
    assert b.read_dependent(ctx.dep3["id"])["coverage_status"] == "TERMINATION_PENDING"


def test_finalization_shifts_it_again_and_the_partition_still_balances(b):
    """The third bucket move leaves the total and the sum untouched.

    PRD: "Every `TerminationNotice` still in `ISSUED` whose `effective_date` is
    strictly earlier than the current clock's calendar date moves `ISSUED →
    FINAL`, and because its notice went final, its dependent moves
    `TERMINATION_PENDING → TERMINATED` with `coverage_end_date` set to that
    notice's `effective_date`."

    Design: Difficulty/compensating_invariant/in_scope_dependent_headcount_conserved_across_amnesty_verification_and_termination
    """
    ctx = _household_with_one_removal_and_one_verification(b)
    b.set_clock(ESCALATION_INSTANT)
    b.sweep(ctx.program["id"])

    b.set_clock(FINALIZE_INSTANT)
    b.sweep(ctx.program["id"])

    program = b.read_program(ctx.program["id"])
    assert counters(program, *PARTITION_FIELDS) == {
        "in_scope_dependent_count": 3,
        "pending_dependent_count": 0,
        "verified_dependent_count": 1,
        "amnesty_removed_count": 1,
        "termination_pending_count": 0,
        "terminated_dependent_count": 1,
    }
    assert_counter_partition(program)

    stepchild = b.read_dependent(ctx.dep3["id"])
    assert stepchild["coverage_status"] == "TERMINATED"
    assert stepchild["coverage_end_date"] == "2026-10-31"
    # The 2026-10-17 notice's appeal window runs to 2026-11-16, so the case waits.
    assert b.read_case(ctx.case["id"])["status"] == "ESCALATED"
    assert program["audited_annual_savings_cents"] == AUDITED_SAVINGS_CENTS
    assert program["provisional_annual_savings_cents"] == PROVISIONAL_SAVINGS_CENTS


# Two medical lines of 240000 and 250000: subtotal 490000, fee 24500 at the five
# percent tier, demand 514500. Two partial payments collect 100000 of it.
RECOVERABLE_CLAIMS = (
    {"service_date": "2026-09-20", "paid_cents": 240000},
    {"service_date": "2026-09-25", "paid_cents": 250000},
)
DEMAND_CENTS = 514500
FIRST_PAYMENT_CENTS = 60000
SECOND_PAYMENT_CENTS = 40000
COLLECTED_CENTS = FIRST_PAYMENT_CENTS + SECOND_PAYMENT_CENTS
FIRST_PAYMENT_INSTANT = "2026-11-02T00:00:00Z"
SECOND_PAYMENT_INSTANT = "2026-11-03T00:00:00Z"
APPEAL_FILED_INSTANT = "2026-11-05T00:00:00Z"


def _partially_collected_demand_with_an_appeal_under_review(b):
    """A demand two payments into collection, with a granted-appeal candidate on file."""
    ctx = recovery_wave(
        b,
        relationships=("SPOUSE",),
        claims=RECOVERABLE_CLAIMS,
        ineligibility_onset_date="2026-09-01",
        issue=True,
    )
    assert ctx.recovery["net_demand_cents"] == DEMAND_CENTS

    b.set_clock(FIRST_PAYMENT_INSTANT)
    b.payment(ctx.recovery["id"], FIRST_PAYMENT_CENTS, received_date="2026-11-02")
    b.set_clock(SECOND_PAYMENT_INSTANT)
    ctx.recovery = b.payment(
        ctx.recovery["id"], SECOND_PAYMENT_CENTS, received_date="2026-11-03"
    )

    b.set_clock(APPEAL_FILED_INSTANT)
    ctx.appeal = b.appeal(
        ctx.case["id"], ctx.dep["id"], ctx.employee["id"], "ADMINISTRATIVE_ERROR"
    )
    ctx.appeal = b.assign_appeal(ctx.appeal["id"], REVIEWER)
    ctx.program = b.read_program(ctx.program["id"])
    return ctx


def test_two_partial_payments_book_the_collected_cash_as_recovered(b):
    """Before the void, every collected cent sits in recovered_total_cents.

    PRD: "`recovered_total_cents` is the sum of `recovered_cents` across those
    recoveries whose `status` is anything other than `VOIDED`."

    Design: Difficulty/compensating_invariant/recovery_cash_conserved_across_demand_payments_and_appeal_void
    """
    ctx = _partially_collected_demand_with_an_appeal_under_review(b)

    assert ctx.recovery["status"] == "PARTIALLY_RECOVERED"
    assert ctx.recovery["recovered_cents"] == COLLECTED_CENTS
    program = ctx.program
    assert program["recovered_total_cents"] == COLLECTED_CENTS
    assert program["refund_due_total_cents"] == 0
    assert (
        program["recovered_total_cents"] + program["refund_due_total_cents"]
        == COLLECTED_CENTS
    )
    assert program["recovery_ledger_cents"] == DEMAND_CENTS


def test_voiding_the_demand_moves_every_collected_cent_to_refund_due(b):
    """The two books still sum to the same cash; the ledger of demands empties.

    PRD: "every `ClaimRecovery` of that dependent whose `status` is `OPEN`,
    `DEMAND_ISSUED`, or `PARTIALLY_RECOVERED` moves to `VOIDED`, and each such
    row's `refund_due_cents` is set equal to its `recovered_cents`"

    Design: Difficulty/compensating_invariant/recovery_cash_conserved_across_demand_payments_and_appeal_void
    """
    ctx = _partially_collected_demand_with_an_appeal_under_review(b)

    b.decide_appeal(ctx.appeal["id"], "GRANT")

    recovery = b.read_recovery(ctx.recovery["id"])
    assert recovery["status"] == "VOIDED"
    assert recovery["recovered_cents"] == COLLECTED_CENTS
    assert recovery["refund_due_cents"] == recovery["recovered_cents"]
    # The demand amount is retained for audit; it merely stops being collectible.
    assert recovery["net_demand_cents"] == DEMAND_CENTS

    program = b.read_program(ctx.program["id"])
    assert program["recovered_total_cents"] == 0
    assert program["refund_due_total_cents"] == COLLECTED_CENTS
    assert (
        program["recovered_total_cents"] + program["refund_due_total_cents"]
        == COLLECTED_CENTS
    )
    assert program["recovery_ledger_cents"] == 0

    assert b.read_dependent(ctx.dep["id"])["coverage_status"] == "REINSTATED"
    assert b.read_notice(ctx.notice["id"])["status"] == "RESCINDED"
