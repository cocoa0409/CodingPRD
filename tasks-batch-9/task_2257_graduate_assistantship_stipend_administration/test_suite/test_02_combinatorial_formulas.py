"""Multi-step money formulas whose intermediate results must not be shortcut.

Both scenarios pick inputs where a plausible but wrong ordering of the steps —
capping before the eligible share, or rounding each line half up instead of
truncating and handing over the remainder — produces a visibly different number.
"""
from test_helpers import (
    allocations_of,
    disbursements_of,
    drive_appointment,
    make_appointment,
    make_department,
    make_funding_source,
    make_pay_periods,
    make_policy,
    make_student,
    make_term,
    open_term,
    schedule_payroll,
    set_funding_plan,
    submit,
)

# --------------------------------------------------------------------------- #
# Remission chain: band, credit cap, gross, eligible share, then the ceiling
# --------------------------------------------------------------------------- #

_REMISSION_PERIOD = [(1, "2026-09-01", "2027-01-01", "2027-01-05")]


def _build_three_source_remission_plan():
    """Two remission-permitting grants and one departmental budget that does not.

    Twelve doctoral credits at 74500 cents each, banded at 75 percent, gross to
    670500; only 60 percent of the plan may carry remission, which funds 402300;
    the policy ceiling of 350000 then bites.
    """
    department = make_department(code="PHYS", name="Physics")
    term = make_term(
        term_code="REM2026", term_start="2026-09-01", term_end="2026-12-31",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-11-15",
    )
    make_policy(
        term["id"], assistantship_type="RESEARCH", degree_level="DOCTORAL",
        min_fte_monthly_stipend_cents=400000,
        per_credit_tuition_cents=74500,
        max_remission_cents_per_term=350000,
        term_insurance_premium_cents=0,
        insurance_min_effort_pct=50,
        min_insurance_duration_days=90,
    )
    make_pay_periods(term["id"], _REMISSION_PERIOD)
    open_term(term["id"])

    student = make_student(
        student_number="GS-REM-001", full_name="Rem Student",
        degree_level="DOCTORAL", is_international=False,
        cumulative_gpa=3.70, enrolled_credit_hours=12,
    )
    nsf = make_funding_source(
        department["id"], source_code="NSF-REM-01", source_type="GRANT",
        authorized_amount_cents=5000000, allows_tuition_remission=True,
    )
    nih = make_funding_source(
        department["id"], source_code="NIH-REM-01", source_type="GRANT",
        authorized_amount_cents=5000000, allows_tuition_remission=True,
    )
    dept_budget = make_funding_source(
        department["id"], source_code="DEPT-REM-01",
        source_type="DEPARTMENTAL_BUDGET",
        authorized_amount_cents=5000000, allows_tuition_remission=False,
    )
    appointment = make_appointment(
        student["id"], department["id"], term["id"],
        assistantship_type="RESEARCH", effort_pct=50,
        start_date="2026-09-01", end_date="2026-12-31",
        monthly_stipend_cents=200000,
    )
    set_funding_plan(appointment["id"], [
        (nsf["id"], 40.00, False),
        (nih["id"], 20.00, False),
        (dept_budget["id"], 40.00, True),
    ])
    submitted = submit(appointment["id"])
    return submitted, allocations_of(appointment["id"], status="PROPOSED")


def test_remission_ceiling_applies_after_the_funding_eligible_share():
    """The policy ceiling clamps the funded remission, not the gross remission.

    PRD: "**Second, the tuition-remission entitlement is derived,** in a step
    order that is pinned: band, then credit cap, then gross, then
    funding-eligible share, then policy ceiling." PRD: "The **remission-eligible
    share** is the sum of `share_pct` over the appointment's allocations whose
    `status` is `PROPOSED` or `COMMITTED` and whose funding source has
    `allows_tuition_remission` true". PRD: "Finally, `tuition_remission_cents`
    is the smaller of the funded remission and the policy's
    `max_remission_cents_per_term`." Applying the 350000 ceiling before the 60
    percent eligible share would instead yield 210000.

    Design: Difficulty/combinatorial_formula/remission_chain_ceiling_after_share_and_remainder_to_first_eligible
    """
    appointment, _ = _build_three_source_remission_plan()

    assert appointment["tuition_remission_pct"] == 75, (
        "50 percent effort sits in the at-least-50, below-75 band"
    )
    assert appointment["tuition_remission_cents"] == 350000, (
        "670500 gross times the 60 percent eligible share is 402300, clamped to "
        "the 350000 policy ceiling"
    )
    assert appointment["tuition_remission_cents"] != 210000, (
        "clamping first and prorating second is the wrong step order"
    )
    assert appointment["total_stipend_cents"] == 200000
    assert appointment["insurance_eligible"] is True


def test_remission_split_hands_the_shortfall_to_the_first_eligible_allocation():
    """The remission divides over eligible allocations only, remainder to the first.

    PRD: "The eligible allocations are ordered by `share_pct` descending and
    then by `plan_sequence` ascending. Each one's `allocated_remission_cents` is
    `tuition_remission_cents` multiplied by that allocation's `share_pct`,
    divided by the remission-eligible share, truncated toward zero to a whole
    cent. The difference between `tuition_remission_cents` and the sum of those
    truncated amounts is handed in its entirety to the first allocation in that
    ordering. Every allocation that is not remission-eligible gets
    `allocated_remission_cents` of 0."

    Design: Difficulty/combinatorial_formula/remission_chain_ceiling_after_share_and_remainder_to_first_eligible
    """
    _, allocations = _build_three_source_remission_plan()

    by_sequence = {a["plan_sequence"]: a for a in allocations}
    assert sorted(by_sequence) == [1, 2, 3]

    assert by_sequence[1]["allocated_remission_cents"] == 233334, (
        "350000 * 40 / 60 truncates to 233333, and the 1-cent shortfall lands "
        "on the largest eligible share"
    )
    assert by_sequence[2]["allocated_remission_cents"] == 116666, "350000 * 20 / 60"
    assert by_sequence[3]["allocated_remission_cents"] == 0, (
        "the departmental budget forbids remission, so it carries none"
    )
    assert sum(a["allocated_remission_cents"] for a in allocations) == 350000


def test_stipend_split_covers_every_allocation_including_the_cost_share_line():
    """The stipend basis divides over all proposed allocations, cost share included.

    PRD: "**Third, the stipend itself is split across sources.** The basis is
    the appointment's `total_stipend_cents`. The allocations whose `status` is
    `PROPOSED` or `COMMITTED` are ordered by `share_pct` descending and then
    `plan_sequence` ascending."

    Design: Difficulty/combinatorial_formula/remission_chain_ceiling_after_share_and_remainder_to_first_eligible
    """
    appointment, allocations = _build_three_source_remission_plan()

    by_sequence = {a["plan_sequence"]: a for a in allocations}
    assert by_sequence[1]["allocated_stipend_cents"] == 80000, "200000 * 40 / 100"
    assert by_sequence[2]["allocated_stipend_cents"] == 40000, "200000 * 20 / 100"
    assert by_sequence[3]["allocated_stipend_cents"] == 80000, (
        "the cost-share line carries stipend even though it carries no remission"
    )
    assert (
        sum(a["allocated_stipend_cents"] for a in allocations)
        == appointment["total_stipend_cents"]
    )


# --------------------------------------------------------------------------- #
# Cost-share split: a basis that does not divide evenly across three shares
# --------------------------------------------------------------------------- #

_COST_SHARE_PERIOD = [(1, "2026-09-01", "2026-10-01", "2026-10-05")]


def _build_uneven_cost_share_plan():
    """A 1020161-cent basis split 40 / 40 / 20 across three sources.

    Truncating each line gives 408064 + 408064 + 204032 = 1020160, one cent
    short, so the pinned ordering decides who absorbs the remainder.
    """
    department = make_department(code="MATH", name="Mathematics")
    term = make_term(
        term_code="CSH2026", term_start="2026-09-01", term_end="2026-09-30",
        tax_calendar_year=2026, session_type="IN_SESSION",
        proration_method="CALENDAR_DAY", remission_drop_deadline="2026-09-15",
    )
    make_policy(
        term["id"], assistantship_type="RESEARCH", degree_level="DOCTORAL",
        min_fte_monthly_stipend_cents=1000000,
        per_credit_tuition_cents=50000,
        max_remission_cents_per_term=500000,
        term_insurance_premium_cents=0,
    )
    make_pay_periods(term["id"], _COST_SHARE_PERIOD)
    open_term(term["id"])

    student = make_student(
        student_number="GS-CSH-001", full_name="Csh Student",
        degree_level="DOCTORAL", is_international=False,
        cumulative_gpa=3.60, enrolled_credit_hours=0,
    )
    nsf = make_funding_source(
        department["id"], source_code="NSF-CSH-01", source_type="GRANT",
        authorized_amount_cents=1000000, allows_tuition_remission=True,
    )
    nih = make_funding_source(
        department["id"], source_code="NIH-CSH-01", source_type="GRANT",
        authorized_amount_cents=1000000, allows_tuition_remission=True,
    )
    dept_budget = make_funding_source(
        department["id"], source_code="DEPT-CSH-01",
        source_type="DEPARTMENTAL_BUDGET",
        authorized_amount_cents=1000000, allows_tuition_remission=True,
    )
    appointment = make_appointment(
        student["id"], department["id"], term["id"],
        assistantship_type="RESEARCH", effort_pct=75,
        start_date="2026-09-01", end_date="2026-09-30",
        monthly_stipend_cents=1020161,
    )
    set_funding_plan(appointment["id"], [
        (nsf["id"], 40.00, False),
        (nih["id"], 40.00, False),
        (dept_budget["id"], 20.00, True),
    ])
    drive_appointment(appointment["id"], "ACTIVE")
    return appointment["id"]


def test_stipend_split_truncates_each_share_then_hands_over_the_whole_remainder():
    """Tied shares are broken by plan_sequence, and the remainder is not spread.

    PRD: "Each allocation's share is computed and truncated toward zero to a
    whole cent; the shortfall between the basis and the sum of the truncated
    shares is then handed in its entirety to the first allocation in a pinned
    ordering. That ordering is `share_pct` descending, and where two allocations
    declare the same `share_pct`, `plan_sequence` ascending."

    Design: Difficulty/combinatorial_formula/cost_share_split_truncate_then_remainder_to_largest_share
    """
    appointment_id = _build_uneven_cost_share_plan()
    schedule_payroll(appointment_id)

    allocations = allocations_of(appointment_id, status="COMMITTED")
    by_sequence = {a["plan_sequence"]: a for a in allocations}
    assert sorted(by_sequence) == [1, 2, 3]

    assert by_sequence[1]["allocated_stipend_cents"] == 408065, (
        "both 40-percent lines truncate to 408064; plan_sequence 1 wins the tie "
        "and takes the 1-cent remainder"
    )
    assert by_sequence[2]["allocated_stipend_cents"] == 408064
    assert by_sequence[3]["allocated_stipend_cents"] == 204032
    assert sum(a["allocated_stipend_cents"] for a in allocations) == 1020161


def test_disbursement_allocation_split_repeats_the_truncate_then_remainder_rule():
    """The scheduled row's per-source split reproduces the plan-level algorithm.

    PRD: "That per-period split uses the same truncate-then-remainder algorithm
    as the plan-level split, with the period's `gross_amount_cents` as the basis
    instead of the appointment's `total_stipend_cents`."

    Design: Difficulty/combinatorial_formula/cost_share_split_truncate_then_remainder_to_largest_share
    """
    appointment_id = _build_uneven_cost_share_plan()
    scheduled = schedule_payroll(appointment_id)

    assert scheduled["payroll_status"] == "SCHEDULED"
    assert scheduled["total_stipend_cents"] == 1020161, (
        "the single pay period covers the whole window, so no proration applies"
    )

    disbursements = disbursements_of(appointment_id)
    assert len(disbursements) == 1
    row = disbursements[0]
    assert row["gross_amount_cents"] == 1020161

    split = {e["plan_sequence"]: e["amount_cents"] for e in row["allocation_split"]}
    assert len(row["allocation_split"]) == 3
    assert split == {1: 408065, 2: 408064, 3: 204032}
    assert sum(split.values()) == 1020161, (
        "the split adds back to the gross exactly, never to 1020160"
    )
