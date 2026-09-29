"""Savings measurement and claims-recovery pricing under their two variants.

Both figures are measured over the identical population, so the whole content of
each pair of variants is in what it includes and where its window opens.
"""
from __future__ import annotations

from test_helpers.constants import MONTHLY_COST_CENTS
from test_helpers.fixtures import (
    ANNOUNCE_INSTANT,
    ESCALATION_INSTANT,
    ORIGIN_INSTANT,
    finalized_wave,
)
from test_helpers.types import Ctx

AMNESTY_REMOVAL_INSTANT = "2026-09-10T00:00:00Z"

# 49713 * 12 for the spouse, 49713 * 12 for the domestic partner and 30500 * 12
# for the amnesty-removed child.
PROVISIONAL_TOTAL_CENTS = 1559112
# Only the amnesty-removed child, prorated by 12 - 9 whole months.
AUDITED_TOTAL_CENTS = 91500


def _two_household_escalated_wave(b) -> Ctx:
    """Two households in one program: one child removed under amnesty, two silent.

    The wave stops with the clock one day past the response deadline and a single
    sweep run, so the spouse and the domestic partner sit in TERMINATION_PENDING
    while the child is already resolved as AMNESTY_REMOVED.
    """
    b.set_clock(ORIGIN_INSTANT)
    employee_one = b.employee()
    employee_two = b.employee()
    spouse = b.dependent(employee_one["id"], "SPOUSE")
    child = b.dependent(employee_one["id"], "CHILD_BIOLOGICAL")
    partner = b.dependent(employee_two["id"], "DOMESTIC_PARTNER")

    program = b.program()
    b.doc_rules(
        program["id"], ("SPOUSE", "CHILD_BIOLOGICAL", "DOMESTIC_PARTNER")
    )
    b.scope(program["id"], "FULL_CENSUS")

    b.set_clock(ANNOUNCE_INSTANT)
    b.communicate(program["id"])
    cases = b.cases(program["id"])
    first_case = next(row for row in cases if row["employee_id"] == employee_one["id"])

    b.set_clock(AMNESTY_REMOVAL_INSTANT)
    b.amnesty_removal(child["id"], first_case["id"], employee_id=employee_one["id"])

    b.set_clock(ESCALATION_INSTANT)
    b.sweep(program["id"])
    return Ctx(
        employee_one=employee_one,
        employee_two=employee_two,
        spouse=spouse,
        child=child,
        partner=partner,
        program=b.read_program(program["id"]),
        cases=b.cases(program["id"]),
    )


def test_provisional_and_audited_savings_diverge_on_the_same_dependent_set(b):
    """Both variants read one population; only their inclusion rules differ.

    PRD: "The `PROVISIONAL` variant includes every in-scope dependent whose
    `coverage_status` is `AMNESTY_REMOVED`, `TERMINATION_PENDING`, or
    `TERMINATED`, and credits each one a full twelve months of its monthly cost
    regardless of when coverage actually ended; the result is written to
    `provisional_annual_savings_cents`."

    Design: Difficulty/dual_variant_calc/savings_provisional_vs_audited_diverge_on_one_dependent_set
    """
    ctx = _two_household_escalated_wave(b)

    b.measure_savings(ctx.program["id"], "PROVISIONAL")
    program = b.measure_savings(ctx.program["id"], "AUDITED")

    assert program["provisional_annual_savings_cents"] == PROVISIONAL_TOTAL_CENTS
    assert program["audited_annual_savings_cents"] == AUDITED_TOTAL_CENTS
    assert (
        program["provisional_annual_savings_cents"]
        - program["audited_annual_savings_cents"]
        == 1467612
    )
    assert program["last_savings_variant"] == "AUDITED"


def test_audited_savings_omits_the_two_dependents_still_under_notice(b):
    """A dependent under notice has saved nothing yet; a removed one is prorated.

    PRD: "The `AUDITED` variant excludes `TERMINATION_PENDING` dependents
    entirely — nothing has actually been saved from a dependent still under
    notice — and prorates each remaining dependent by twelve minus the calendar
    month number of that dependent's `coverage_end_date`, so a dependent whose
    coverage ended on the last day of September, month nine, contributes three
    months of its monthly cost."

    Design: Difficulty/dual_variant_calc/savings_provisional_vs_audited_diverge_on_one_dependent_set
    """
    ctx = _two_household_escalated_wave(b)

    spouse = b.read_dependent(ctx.spouse["id"])
    partner = b.read_dependent(ctx.partner["id"])
    child = b.read_dependent(ctx.child["id"])
    assert spouse["coverage_status"] == "TERMINATION_PENDING"
    assert partner["coverage_status"] == "TERMINATION_PENDING"
    assert child["coverage_status"] == "AMNESTY_REMOVED"
    assert child["coverage_end_date"] == "2026-09-30"

    program = b.measure_savings(ctx.program["id"], "AUDITED")

    assert program["audited_annual_savings_cents"] == (
        MONTHLY_COST_CENTS["CHILD_BIOLOGICAL"] * (12 - 9)
    )
    assert program["last_savings_variant"] == "AUDITED"


def test_measuring_savings_records_the_variant_that_was_requested(b):
    """The requested variant is stored, so a later measurement overwrites it.

    PRD: "A `ProgramAdmin` may ask the program to measure savings at any time,
    supplying a `variant` of `PROVISIONAL` or `AUDITED`; the requested variant is
    recorded in `last_savings_variant` and the corresponding figure is written."

    Design: Difficulty/dual_variant_calc/savings_provisional_vs_audited_diverge_on_one_dependent_set
    """
    ctx = _two_household_escalated_wave(b)

    audited = b.measure_savings(ctx.program["id"], "AUDITED")
    assert audited["last_savings_variant"] == "AUDITED"
    assert audited["audited_annual_savings_cents"] == AUDITED_TOTAL_CENTS

    provisional = b.measure_savings(ctx.program["id"], "PROVISIONAL")
    assert provisional["last_savings_variant"] == "PROVISIONAL"
    assert provisional["provisional_annual_savings_cents"] == PROVISIONAL_TOTAL_CENTS
    # The audited figure the earlier call booked is not disturbed by the later one.
    assert provisional["audited_annual_savings_cents"] == AUDITED_TOTAL_CENTS


# The same three paid lines are priced under both recovery variants.
RECOVERY_CLAIMS = (
    {"service_date": "2026-07-15", "paid_cents": 120000, "employee_premium_offset_cents": 20000},
    {"service_date": "2026-09-20", "paid_cents": 150000, "employee_premium_offset_cents": 30000},
    {"service_date": "2026-11-15", "paid_cents": 50000, "employee_premium_offset_cents": 0},
)
ONSET_DATE = "2026-06-01"
STRICT_SUBTOTAL_CENTS = 270000
EQUITABLE_SUBTOTAL_CENTS = 120000


def _terminated_dependent_with_claims(b) -> Ctx:
    """A finalised termination whose dependent carries the three paid lines."""
    ctx = finalized_wave(b, claims=list(RECOVERY_CLAIMS))
    ctx.dep = b.read_dependent(ctx.dep["id"])
    ctx.notice = b.notice_for(ctx.dep["id"])
    return ctx


def test_strict_recovery_reaches_back_to_the_ineligibility_onset_date(b):
    """The July line is inside the strict window and its offset is ignored.

    PRD: "Under `STRICT`, the window opens at the supplied
    `ineligibility_onset_date` and each qualifying line contributes its full
    `paid_cents`: this is the gross plan-paid amount reaching all the way back to
    the date the dependent actually became ineligible, and employee premium
    contributions are ignored entirely."

    Design: Difficulty/dual_variant_calc/recovery_strict_vs_equitable_diverge_on_one_claim_line_set
    """
    ctx = _terminated_dependent_with_claims(b)
    assert ctx.dep["coverage_status"] == "TERMINATED"
    assert ctx.dep["coverage_end_date"] == "2026-10-31"

    recovery = b.open_recovery(
        ctx.dep["id"], ctx.notice["id"], "STRICT", ONSET_DATE
    )

    assert recovery["recoverable_subtotal_cents"] == STRICT_SUBTOTAL_CENTS
    assert recovery["recovery_variant"] == "STRICT"
    assert recovery["status"] == "OPEN"
    assert recovery["admin_fee_cents"] == 0
    assert recovery["net_demand_cents"] == 0


def test_equitable_recovery_opens_at_the_announcement_date_and_nets_each_line(b):
    """The pre-announcement line drops out and the September line is netted.

    PRD: "Under `EQUITABLE`, the window instead opens at the calendar date of the
    program's `announcement_at` — the date the employer told the population an
    audit was happening, rather than the date the ineligibility began — and each
    qualifying line contributes its `paid_cents` reduced by its
    `employee_premium_offset_cents`, with any line whose offset exceeds its paid
    amount contributing zero rather than a negative number."

    Design: Difficulty/dual_variant_calc/recovery_strict_vs_equitable_diverge_on_one_claim_line_set
    """
    ctx = _terminated_dependent_with_claims(b)

    strict = b.open_recovery(ctx.dep["id"], ctx.notice["id"], "STRICT", ONSET_DATE)
    equitable = b.open_recovery(
        ctx.dep["id"], ctx.notice["id"], "EQUITABLE", ONSET_DATE
    )

    assert equitable["recoverable_subtotal_cents"] == EQUITABLE_SUBTOTAL_CENTS
    assert (
        strict["recoverable_subtotal_cents"]
        - equitable["recoverable_subtotal_cents"]
        == 150000
    )


def test_the_november_line_falls_outside_the_closed_window_under_both_variants(b):
    """The window closes at the dependent's coverage end date, so a later line pays nothing.

    PRD: "The window closes at the dependent's `coverage_end_date` when that
    field is set, and at the notice's `effective_date` when it is not."

    Design: Difficulty/dual_variant_calc/recovery_strict_vs_equitable_diverge_on_one_claim_line_set
    """
    ctx = _terminated_dependent_with_claims(b)
    # 120000 + 150000 + 50000 were paid in total; only the first two are inside
    # the window that closes on 2026-10-31.
    assert ctx.dep["paid_claims_total_cents"] == 320000

    strict = b.open_recovery(ctx.dep["id"], ctx.notice["id"], "STRICT", ONSET_DATE)

    assert strict["recoverable_subtotal_cents"] == STRICT_SUBTOTAL_CENTS
    assert strict["recoverable_subtotal_cents"] < ctx.dep["paid_claims_total_cents"]


def test_opening_a_second_recovery_supersedes_the_uncollected_first_row(b):
    """A re-priced recovery retires the row it replaces and bumps the revision.

    PRD: "Creation also supersedes: any prior recovery of the same dependent
    whose `status` is `OPEN`, or whose `status` is `DEMAND_ISSUED` with
    `recovered_cents` still exactly zero, moves to `SUPERSEDED`, and the
    program's `recovery_ledger_cents` is recomputed so the superseded row no
    longer counts."

    Design: Difficulty/dual_variant_calc/recovery_strict_vs_equitable_diverge_on_one_claim_line_set
    """
    ctx = _terminated_dependent_with_claims(b)

    strict = b.open_recovery(ctx.dep["id"], ctx.notice["id"], "STRICT", ONSET_DATE)
    equitable = b.open_recovery(
        ctx.dep["id"], ctx.notice["id"], "EQUITABLE", ONSET_DATE
    )

    assert b.read_recovery(strict["id"])["status"] == "SUPERSEDED"
    assert b.read_recovery(equitable["id"])["status"] == "OPEN"
    assert b.read_dependent(ctx.dep["id"])["recovery_revision"] == 2
    # Neither row has been priced, so the demand ledger stays empty.
    assert b.read_program(ctx.program["id"])["recovery_ledger_cents"] == 0
