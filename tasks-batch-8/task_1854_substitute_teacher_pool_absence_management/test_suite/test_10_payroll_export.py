"""Payroll periods and the export waterfall: empty-period export and terminal
lockout, export gating on timesheet/assignment states, and the budget-capped
waterfall with pinned evaluation order."""
from test_helpers import (
    ApiErrorId,
    export_period,
    get_absence,
    get_assignment,
    get_school,
    make_coordinator_headers,
    make_district,
    open_payroll_period,
    review_timesheet,
    submit_timesheet,
    validate_error,
    validate_success,
    verified_assignment_ctx,
    verify_assignment_ok,
    worked_assignment_ctx,
)


def test_payroll_export_empty_period_and_double_export_lockout(api, payroll_clerk_headers):
    """PRD 3.7: "The period records `total_payout_cents` as the sum of charged
    assignment payouts plus compensation, `assignments_paid_count` and
    `coverages_compensated_count` as their names promise, and `exported_at`
    from the logical clock, ending `EXPORTED`."
    PRD 3.7: "The period must be `OPEN`; there must be no `SUBMITTED`
    timesheet attached to any assignment whose absence belongs to the
    district; and there must be no assignment still `ACCEPTED` or `WORKED`
    whose absence's `end_date` falls inside the period window — all three
    violations surface as `ERR_PAYROLL_PERIOD_INVALID_STATE`"

    Design: Corner/endpoints/payroll_export_empty_period_and_double_export_lockout
    """
    district = make_district()
    period = open_payroll_period(district["id"], "2026-08-03", "2026-08-07")

    exported = export_period(period["id"])
    assert exported["status"] == "EXPORTED"
    assert exported["total_payout_cents"] == 0
    assert exported["assignments_paid_count"] == 0
    assert exported["coverages_compensated_count"] == 0
    assert isinstance(exported["exported_at"], str) and exported["exported_at"]

    res = api.export_payroll_period(period["id"], payroll_clerk_headers)
    validate_error(res, ApiErrorId.ERR_PAYROLL_PERIOD_INVALID_STATE, expected_status=409)


def _capped_waterfall_ctx():
    """Sub rate 5000; absence Mon 2026-08-03..Fri 2026-08-14 (10 weekdays,
    district-approved); school budget 50500 (provisional 50000 commits,
    available 500); all 10 days approved and verified (final 50750 after
    day-10 long-term conversion). Payroll period 2026-08-03..2026-08-14 OPEN."""
    ctx = verified_assignment_ctx(
        start_date="2026-08-03",
        end_date="2026-08-14",
        sub_rate=5000,
        budget=50_500,
    )
    ctx["period"] = open_payroll_period(ctx["district"]["id"], "2026-08-03", "2026-08-14")
    return ctx


def test_payroll_waterfall_caps_charge_at_available_budget(api):
    """PRD 3.7: "For each, in order: the school's committed budget releases
    the assignment's full `provisional_pay_cents` reserve; the charge is the
    assignment's `final_payout_cents` clamped to the school's available budget
    after that release; the charged amount is added to the school's spent
    budget; the assignment's `final_payout_cents` itself is left unchanged at
    its uncapped value while `payout_capped` records whether the charge fell
    short"

    Design: Difficulty/combinatorial_formula/payroll_waterfall_cap_evaluation_order
    """
    ctx = _capped_waterfall_ctx()
    assert ctx["assignment"]["final_payout_cents"] == 50750, (
        "9 x 5000 + round_half_up(5000 x 1.15) after the day-10 conversion"
    )

    export_period(ctx["period"]["id"])

    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "PAID"
    assert assignment["payout_capped"] is True, "charge 50500 fell short of final 50750"
    assert assignment["final_payout_cents"] == 50750, "uncapped value is left unchanged"

    school = get_school(ctx["school"]["id"])
    assert school["coverage_budget_committed_cents"] == 0, "reserve released first"
    assert school["coverage_budget_spent_cents"] == 50500, (
        "charge = min(50750, 50500 available after release)"
    )
    assert school["coverage_budget_available_cents"] == 0


def test_payroll_waterfall_records_period_totals_and_closes_absence(api):
    """PRD 3.7: "Every `COMPLETED` absence whose assignment was just paid
    closes to `CLOSED`. The period records `total_payout_cents` as the sum of
    charged assignment payouts plus compensation, `assignments_paid_count` and
    `coverages_compensated_count` as their names promise, and `exported_at`
    from the logical clock, ending `EXPORTED`."

    Design: Difficulty/combinatorial_formula/payroll_waterfall_cap_evaluation_order
    """
    ctx = _capped_waterfall_ctx()
    exported = export_period(ctx["period"]["id"])
    assert exported["status"] == "EXPORTED"
    assert exported["total_payout_cents"] == 50500
    assert exported["assignments_paid_count"] == 1
    assert exported["coverages_compensated_count"] == 0
    assert isinstance(exported["exported_at"], str) and exported["exported_at"]
    assert get_absence(ctx["absence"]["id"])["fill_status"] == "CLOSED"


def _submitted_timesheet_blocking_export_ctx():
    """1-day absence Mon 2026-08-03 filled, reported WORKED, one timesheet
    left SUBMITTED; payroll period 2026-08-03..2026-08-07 OPEN."""
    ctx = worked_assignment_ctx(start_date="2026-08-03", end_date="2026-08-03")
    ctx["timesheet"] = submit_timesheet(
        ctx["assignment"]["id"], ctx["sub"]["id"], "2026-08-03"
    )
    ctx["period"] = open_payroll_period(ctx["district"]["id"], "2026-08-03", "2026-08-07")
    return ctx


def test_payroll_export_blocked_by_submitted_timesheet(api, payroll_clerk_headers):
    """PRD 3.7: "The period must be `OPEN`; there must be no `SUBMITTED`
    timesheet attached to any assignment whose absence belongs to the
    district; and there must be no assignment still `ACCEPTED` or `WORKED`
    whose absence's `end_date` falls inside the period window — all three
    violations surface as `ERR_PAYROLL_PERIOD_INVALID_STATE`, the latter two
    because export would otherwise strand unreviewed work mid-period."

    Design: Difficulty/cross_entity_state_dependency/payroll_export_gated_by_timesheet_states
    """
    ctx = _submitted_timesheet_blocking_export_ctx()
    res = api.export_payroll_period(ctx["period"]["id"], payroll_clerk_headers)
    validate_error(res, ApiErrorId.ERR_PAYROLL_PERIOD_INVALID_STATE, expected_status=409)

    period = validate_success(api.get_payroll_period(ctx["period"]["id"], payroll_clerk_headers), 200)
    assert period["status"] == "OPEN", "no partial export occurred"
    assert period["total_payout_cents"] is None

    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "WORKED", "untouched by the rejected export"


def test_payroll_export_unblocked_once_review_finishes(api):
    """PRD 3.7: "A clean export runs the waterfall. In scope are the
    district's `VERIFIED` assignments whose absence's `end_date` falls within
    the period, processed strictly in order of assignment `created_at`
    ascending — the pinned tie-break, never `id` — because each assignment's
    charge depends on the budget left by those before it."
    PRD 3.5: "A coordinator or district admin verifies a `WORKED` assignment —
    any other status, or the existence of any still-`SUBMITTED` timesheet,
    fails with `ERR_ASSIGNMENT_INVALID_STATE`, forcing review to finish
    first."

    Design: Difficulty/cross_entity_state_dependency/payroll_export_gated_by_timesheet_states
    """
    ctx = _submitted_timesheet_blocking_export_ctx()
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    review_timesheet(ctx["timesheet"]["id"], "APPROVE", coord_headers)
    verify_assignment_ok(ctx["assignment"]["id"], coord_headers)

    exported = export_period(ctx["period"]["id"])
    assert exported["status"] == "EXPORTED"
    assert exported["assignments_paid_count"] == 1
    assert exported["total_payout_cents"] == 20000
    assert get_assignment(ctx["assignment"]["id"])["status"] == "PAID"
    assert get_absence(ctx["absence"]["id"])["fill_status"] == "CLOSED"
