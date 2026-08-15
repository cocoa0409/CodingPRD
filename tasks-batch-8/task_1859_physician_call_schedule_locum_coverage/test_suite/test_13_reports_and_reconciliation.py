"""Computed reports (fairness and coverage) and end-of-period reconciliation."""
from test_helpers import (
    ApiErrorId,
    assert_pay_entry,
    assign_staff,
    create_published_program,
    create_staff_physician,
    fairness_entry_for,
    get_coverage_report,
    get_fairness_report,
    get_slot_for_date,
    numeric_values,
    serve_assignment,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Fairness report: prospective vs actual variants ─────────────────

def _setup_fairness_program():
    """PUBLISHED program 2026-09-08..2026-09-13 (one primary per weekday and
    per weekend day, no backups); P1 holds 2026-09-08 (weekday, 1.0) and
    2026-09-12 (Saturday, 2.0) with the weekday one SERVED; P2 holds
    2026-09-09 (weekday, 1.0) still SCHEDULED."""
    program = create_published_program(
        name="Cards Sep W2",
        period_start="2026-09-08",
        period_end="2026-09-13",
        payroll_budget_cents=1_000_000,
        weekday_primary_required=1,
        weekend_primary_required=1,
    )
    p1 = create_staff_physician("Dr Alvarez")
    p2 = create_staff_physician("Dr Becker")
    a1 = assign_staff(get_slot_for_date(program["id"], "2026-09-08")["id"], p1["id"])
    assign_staff(get_slot_for_date(program["id"], "2026-09-12")["id"], p1["id"])
    assign_staff(get_slot_for_date(program["id"], "2026-09-09")["id"], p2["id"])
    set_clock("2026-09-09T08:00:00Z")  # past the 2026-09-08 window end
    serve_assignment(a1["id"])
    return program, p1, p2, a1


def test_fairness_points_prospective_vs_actual_totals(api):
    """PRD §3.6: "it returns the `program_id`, the `population_size`,
    `total_prospective_points` and `total_actual_points` across that population,
    `mean_prospective_points` and `mean_actual_points` — each mean being the
    corresponding total divided by the population size, rounded half-up to two
    decimal places — the program's `equity_band_points`, and the per-physician
    `entries`."
    PRD §2.8: "Prospective points sum the physician's assignments in SCHEDULED,
    ACTIVATED, or SERVED status. Actual points sum SERVED assignments only".

    Design: Difficulty/dual_variant_calc/fairness_points_prospective_vs_actual
    """
    program, _p1, _p2, _a1 = _setup_fairness_program()
    report = get_fairness_report(program["id"])
    assert report["program_id"] == program["id"]
    assert report["population_size"] == 2
    assert report["total_prospective_points"] == 4.0
    assert report["total_actual_points"] == 1.0
    assert report["mean_prospective_points"] == 2.0
    assert report["mean_actual_points"] == 0.5
    assert report["equity_band_points"] == 4.0


def test_fairness_points_per_physician_variant_divergence(api):
    """PRD §2.8: "Actual points sum SERVED assignments only, so identical data
    always yields actual totals less than or equal to prospective totals."

    P1: 3.0 prospective (SERVED weekday 1.0 + SCHEDULED Saturday 2.0) vs 1.0
    actual; P2: 1.0 prospective vs 0.0 actual.

    Design: Difficulty/dual_variant_calc/fairness_points_prospective_vs_actual
    """
    program, p1, p2, _a1 = _setup_fairness_program()
    report = get_fairness_report(program["id"])
    entry_p1 = fairness_entry_for(report, p1["id"])
    entry_p2 = fairness_entry_for(report, p2["id"])
    nums_p1 = numeric_values(entry_p1)
    nums_p2 = numeric_values(entry_p2)
    assert 3.0 in nums_p1 and 1.0 in nums_p1, (
        f"P1 entry must carry 3.0 prospective and 1.0 actual: {entry_p1!r}"
    )
    assert 1.0 in nums_p2 and 0.0 in nums_p2, (
        f"P2 entry must carry 1.0 prospective and 0.0 actual: {entry_p2!r}"
    )
    assert report["total_actual_points"] <= report["total_prospective_points"]


# ─── Coverage report ─────────────────────────────────────────────────

def test_coverage_report_shortfall_and_exact_equality(api):
    """PRD §3.6: "A date is compliant when its covered primary count meets or
    exceeds the required primary count and its covered backup count meets or
    exceeds the required backup count — exact coverage counts as compliant. The
    report returns the `program_id`, the `compliant_date_count`, the
    `noncompliant_date_count`, the `open_gap_count` — gaps still in OPEN or
    REQUISITIONED status".

    2026-09-08 has 1 of 2 primaries covered (noncompliant); 2026-09-09 has
    exactly 2 of 2 (compliant); one gap remains open.

    Design: Corner/calculations/coverage_report_shortfall_and_exact_equality
    """
    program = create_published_program(
        name="Cards Coverage",
        period_start="2026-09-08",
        period_end="2026-09-09",
        weekday_primary_required=2,
    )
    p1 = create_staff_physician("Dr A")
    p2 = create_staff_physician("Dr B")
    assign_staff(get_slot_for_date(program["id"], "2026-09-08", index=0)["id"], p1["id"])
    assign_staff(get_slot_for_date(program["id"], "2026-09-09", index=0)["id"], p1["id"])
    assign_staff(get_slot_for_date(program["id"], "2026-09-09", index=1)["id"], p2["id"])

    report = get_coverage_report(program["id"])
    assert report["program_id"] == program["id"]
    assert report["compliant_date_count"] == 1
    assert report["noncompliant_date_count"] == 1
    assert report["open_gap_count"] == 1


# ─── Reconciliation ──────────────────────────────────────────────────

def _setup_reconcile_happy():
    """PUBLISHED two-day program; P1 assigned to 2026-09-08 and SERVED; the
    2026-09-09 slot never filled (gap OPEN); clock at 2026-09-10T00:00:00Z —
    exactly 00:00:00 on the day after period_end."""
    program = create_published_program(
        name="Cards Reconcile", period_start="2026-09-08", period_end="2026-09-09"
    )
    physician = create_staff_physician("Dr A")
    slot_0908 = get_slot_for_date(program["id"], "2026-09-08")
    slot_0909 = get_slot_for_date(program["id"], "2026-09-09")
    assignment = assign_staff(slot_0908["id"], physician["id"])
    set_clock("2026-09-09T08:00:00Z")
    serve_assignment(assignment["id"])
    set_clock("2026-09-10T00:00:00Z")
    return program, slot_0908, slot_0909, assignment


def test_reconcile_happy_path_finalizes_pay_and_covers_slots(api):
    """PRD §3.6: "Reconciliation moves every ACCRUED pay entry to FINALIZED,
    moves every slot still OPEN to UNCOVERED, and increments the program
    `version`."
    PRD §3.6: "requires the logical clock to have reached 00:00:00 UTC on the
    day after `period_end` (`ERR_PERIOD_NOT_ENDED`)" — the clock here is exactly
    at that boundary, which 'reached' permits.

    Design: Corner/state_machines/reconcile_happy_path_finalizes_pay_and_covers_slots
    """
    program, slot_0908, slot_0909, assignment = _setup_reconcile_happy()
    resp = api.reconcile_program(program["id"], ADMIN)
    reconciled = validate_success(resp, 200)
    assert reconciled["status"] == "RECONCILED"

    entries, _meta = validate_paginated(
        api.list_pay_entries(ADMIN, params={"assignment_id": assignment["id"]})
    )
    assert len(entries) == 1
    assert_pay_entry(entries[0])
    assert entries[0]["status"] == "FINALIZED"
    assert entries[0]["amount_cents"] == 50000

    covered = validate_success(api.get_slot(slot_0908["id"], ADMIN))
    assert covered["status"] == "COVERED"
    uncovered = validate_success(api.get_slot(slot_0909["id"], ADMIN))
    assert uncovered["status"] == "UNCOVERED"

    gaps, _meta = validate_paginated(
        api.list_gaps(ADMIN, params={"slot_id": slot_0909["id"], "status": "OPEN"})
    )
    assert len(gaps) == 1, "the unfilled slot's gap remains OPEN as a historical record"


def test_reconcile_before_period_end_rejected(api):
    """PRD §3.6: "requires the logical clock to have reached 00:00:00 UTC on the
    day after `period_end` (`ERR_PERIOD_NOT_ENDED`)".

    The clock is 2026-09-09T12:00:00Z — before 2026-09-10T00:00:00Z.

    Design: Corner/validations/reconcile_before_period_end_rejected
    """
    program = create_published_program(
        period_start="2026-09-08", period_end="2026-09-09"
    )
    physician = create_staff_physician("Dr A")
    slot = get_slot_for_date(program["id"], "2026-09-08")
    assignment = assign_staff(slot["id"], physician["id"])
    set_clock("2026-09-09T08:00:00Z")
    serve_assignment(assignment["id"])
    set_clock("2026-09-09T12:00:00Z")

    resp = api.reconcile_program(program["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_ENDED, 409)
    after = validate_success(api.get_program(program["id"], ADMIN))
    assert after["status"] == "PUBLISHED"


def test_reconcile_with_unresolved_assignment_rejected(api):
    """PRD §3.6: "requires every assignment in the program to be terminal —
    SERVED, SWAPPED, or CANCELLED — (`ERR_UNRESOLVED_ASSIGNMENTS_EXIST`)".

    Design: Corner/validations/reconcile_with_unresolved_assignment_rejected
    """
    program = create_published_program(
        period_start="2026-09-08", period_end="2026-09-08"
    )
    physician = create_staff_physician("Dr A")
    slot = get_slot_for_date(program["id"], "2026-09-08")
    assign_staff(slot["id"], physician["id"])
    set_clock("2026-09-10T00:00:00Z")  # period over, assignment still SCHEDULED

    resp = api.reconcile_program(program["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST, 409)
    after = validate_success(api.get_program(program["id"], ADMIN))
    assert after["status"] == "PUBLISHED"
