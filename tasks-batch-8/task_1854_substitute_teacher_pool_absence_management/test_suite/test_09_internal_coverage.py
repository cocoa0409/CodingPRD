"""Internal coverage of unfilled absences: the UNFILLED <-> COVERED_INTERNALLY
cycle, reject/confirm terminal rules, the confirm-worked rate snapshot,
aggregate daily/weekly capacity semantics, and day-count conservation."""
from test_helpers import (
    ApiErrorId,
    assert_absence_day_conservation,
    basic_world,
    cancel_coverage,
    confirm_coverage_worked,
    get_absence,
    make_coordinator_headers,
    make_district_admin_headers,
    make_staff,
    propose_coverage,
    report_absence,
    review_coverage,
    run_dispatch_batch,
    set_logical_clock,
    unfilled_absence_ctx,
    validate_error,
    validate_success,
)


def test_coverage_reject_branch_and_terminal_rules(api):
    """PRD 3.6: "Rejection simply moves the proposal to `REJECTED`."
    PRD 3.6: "After the day passes, the coordinator confirms the coverage was
    worked — the coverage must be `APPROVED` and the clock date must have
    reached the `coverage_date`, both failing as
    `ERR_COVERAGE_INVALID_STATE`"
    PRD 3.6: "at which point `compensation_cents` is fixed as `periods` times
    the district's `period_comp_rate_cents`, the rate read and snapshotted at
    confirmation time so later district reconfiguration never rewrites
    history."

    Design: Corner/state_machines/coverage_reject_branch_and_terminal_rules
    """
    ctx = unfilled_absence_ctx(run_for_date="2026-08-04")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    coverage = propose_coverage(
        ctx["absence"]["id"], ctx["covering_teacher"]["id"], "2026-08-03", 2, coord_headers
    )
    rejected = review_coverage(coverage["id"], "REJECT")
    assert rejected["status"] == "REJECTED"

    res = api.confirm_coverage_worked(coverage["id"], coord_headers)
    validate_error(res, ApiErrorId.ERR_COVERAGE_INVALID_STATE, expected_status=409)

    refreshed = validate_success(
        api.get_internal_coverage(coverage["id"], make_district_admin_headers()), 200
    )
    assert refreshed["status"] == "REJECTED"
    assert refreshed["compensation_cents"] is None, "no compensation without confirmation"


def test_coverage_compensation_rate_snapshot_at_confirm_worked(api, district_admin_headers):
    """PRD 3.6: "at which point `compensation_cents` is fixed as `periods`
    times the district's `period_comp_rate_cents`, the rate read and
    snapshotted at confirmation time so later district reconfiguration never
    rewrites history."

    Design: Corner/calculations/coverage_compensation_rate_snapshot_at_confirm_worked
    """
    ctx = unfilled_absence_ctx(run_for_date="2026-08-04")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    coverage = propose_coverage(
        ctx["absence"]["id"], ctx["covering_teacher"]["id"], "2026-08-03", 4, coord_headers
    )
    review_coverage(coverage["id"], "APPROVE")

    district = validate_success(api.get_district(ctx["district"]["id"], district_admin_headers), 200)
    validate_success(
        api.update_district(
            district["id"],
            {"expected_district_version": district["version"],
             "period_comp_rate_cents": 3000},
            district_admin_headers,
        ),
        200,
    )
    set_logical_clock("2026-08-04T12:00:00Z")

    worked = confirm_coverage_worked(coverage["id"], coord_headers)
    assert worked["status"] == "WORKED"
    assert worked["compensation_cents"] == 12000, (
        "4 periods x 3000 — the rate live at confirm-worked, not the 2500 at approval"
    )


def test_unfilled_to_covered_internally_on_first_approval(api):
    """PRD 3.4: "Second, the cutoff sweep: a `DISPATCHING` absence whose
    `start_date` is on or before the batch run date, with no assignment ever
    `ACCEPTED`, `WORKED`, or `VERIFIED` and no live `OFFERED` assignment
    remaining, is marked `UNFILLED`."
    PRD 3.6: "on success the absence's `days_covered_internal` is recomputed,
    and the first approved coverage moves the absence from `UNFILLED` to
    `COVERED_INTERNALLY`."

    Design: Difficulty/non_linear_state_machine/absence_unfilled_internal_coverage_cycle
    """
    ctx = unfilled_absence_ctx(run_for_date="2026-08-04")
    assert ctx["batch"]["offers_created"] == 0, "empty pool: no offer created"
    assert ctx["batch"]["absences_marked_unfilled"] == 1
    assert ctx["absence"]["fill_status"] == "UNFILLED"

    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    coverage = propose_coverage(
        ctx["absence"]["id"], ctx["covering_teacher"]["id"], "2026-08-03", 2, coord_headers
    )
    review_coverage(coverage["id"], "APPROVE")

    absence = get_absence(ctx["absence"]["id"])
    assert absence["fill_status"] == "COVERED_INTERNALLY"
    assert absence["days_covered_internal"] == 1
    assert absence["days_covered_sub"] == 0
    assert absence["days_uncovered"] == 0
    assert_absence_day_conservation(absence)


def test_covered_internally_loops_back_to_unfilled_on_last_cancel(api):
    """PRD 3.6: "cancelling an `APPROVED` one decrements the absence's
    internal-day count, and when that count reaches zero the absence falls
    back from `COVERED_INTERNALLY` to `UNFILLED`, eligible for dispatch
    again."
    PRD 3.6: "The conservation invariant holds at all times: internal days
    plus substitute days plus uncovered days exactly equal `total_days`."

    Design: Difficulty/non_linear_state_machine/absence_unfilled_internal_coverage_cycle
    """
    ctx = unfilled_absence_ctx(run_for_date="2026-08-04")
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    coverage = propose_coverage(
        ctx["absence"]["id"], ctx["covering_teacher"]["id"], "2026-08-03", 2, coord_headers
    )
    review_coverage(coverage["id"], "APPROVE")
    assert get_absence(ctx["absence"]["id"])["fill_status"] == "COVERED_INTERNALLY"

    cancelled = cancel_coverage(coverage["id"], coord_headers)
    assert cancelled["status"] == "CANCELLED"

    absence = get_absence(ctx["absence"]["id"])
    assert absence["fill_status"] == "UNFILLED", "the last approved coverage dissolved"
    assert absence["days_covered_internal"] == 0
    assert absence["days_covered_sub"] == 0
    assert absence["days_uncovered"] == 1
    assert_absence_day_conservation(absence)


def _three_unfilled_absences_ctx():
    """T1 (SCIENCE) absent Mon 2026-08-03, Tue 2026-08-04, Wed 2026-08-05;
    no substitutes; one batch run on 2026-08-05 marks all three UNFILLED.
    T2 (MATH) is the covering teacher."""
    ctx = basic_world(teacher_subject="SCIENCE")
    ctx["covering_teacher"] = make_staff(
        ctx["school"]["id"], full_name="Teach Two", subject="MATH", grade_band="HIGH"
    )
    absences = [
        report_absence(
            ctx["teacher"], start_date=day, end_date=day, required_subject="SCIENCE"
        )
        for day in ("2026-08-03", "2026-08-04", "2026-08-05")
    ]
    ctx["batch"] = run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-08-05")
    ctx["absences"] = [get_absence(a["id"]) for a in absences]
    return ctx


def test_coverage_capacity_daily_cap_inclusive_then_breached(api):
    """PRD 3.6: "the sum of `periods` across their coverages in `PROPOSED`,
    `APPROVED`, `WORKED`, or `COMPENSATED` on the same calendar date may not
    exceed the district's `daily_period_cap` (8 by default), and the same sum
    across the ISO week (Monday through Sunday) containing that date may not
    exceed the `weekly_period_cap` (10 by default); a breach is
    `ERR_COVERAGE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/internal_coverage_aggregate_capacity_semantics
    """
    ctx = _three_unfilled_absences_ctx()
    assert ctx["batch"]["absences_marked_unfilled"] == 3
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    abs_mon = ctx["absences"][0]

    full_day = propose_coverage(
        abs_mon["id"], ctx["covering_teacher"]["id"], "2026-08-03", 8, coord_headers
    )
    assert full_day["status"] == "PROPOSED"
    assert full_day["periods"] == 8, "the daily cap 8 is inclusive: 8 <= 8 passes"

    res = api.create_internal_coverage(
        {"absence_id": abs_mon["id"], "staff_member_id": ctx["covering_teacher"]["id"],
         "coverage_date": "2026-08-03", "periods": 1},
        coord_headers,
    )
    validate_error(res, ApiErrorId.ERR_COVERAGE_CAPACITY_EXCEEDED, expected_status=409)


def test_coverage_capacity_weekly_cap_binds_across_days(api):
    """PRD 3.6: "the sum of `periods` across their coverages in `PROPOSED`,
    `APPROVED`, `WORKED`, or `COMPENSATED` on the same calendar date may not
    exceed the district's `daily_period_cap` (8 by default), and the same sum
    across the ISO week (Monday through Sunday) containing that date may not
    exceed the `weekly_period_cap` (10 by default); a breach is
    `ERR_COVERAGE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/internal_coverage_aggregate_capacity_semantics
    """
    ctx = _three_unfilled_absences_ctx()
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    abs_mon, abs_tue, abs_wed = ctx["absences"]

    propose_coverage(abs_mon["id"], ctx["covering_teacher"]["id"], "2026-08-03", 8, coord_headers)
    tuesday = propose_coverage(
        abs_tue["id"], ctx["covering_teacher"]["id"], "2026-08-04", 2, coord_headers
    )
    assert tuesday["status"] == "PROPOSED", "weekly total 8 + 2 == 10 <= 10 passes"

    res = api.create_internal_coverage(
        {"absence_id": abs_wed["id"], "staff_member_id": ctx["covering_teacher"]["id"],
         "coverage_date": "2026-08-05", "periods": 1},
        coord_headers,
    )
    validate_error(res, ApiErrorId.ERR_COVERAGE_CAPACITY_EXCEEDED, expected_status=409)


def test_day_conservation_across_approvals(api):
    """PRD 3.6: "`days_covered_internal` counts the distinct coverage dates
    whose coverage stands in `APPROVED`, `WORKED`, or `COMPENSATED`;
    `days_covered_sub` is the verified assignment's `worked_days_count`, or
    zero while no assignment has reached `VERIFIED`; and `days_uncovered` is
    whatever remains."
    PRD 3.6: "The conservation invariant holds at all times: internal days
    plus substitute days plus uncovered days exactly equal `total_days`."

    Design: Difficulty/compensating_invariant/absence_day_coverage_conservation_across_approve_and_cancel
    """
    ctx = unfilled_absence_ctx(
        start_date="2026-08-03", end_date="2026-08-07", run_for_date="2026-08-05"
    )
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    mon = propose_coverage(
        ctx["absence"]["id"], ctx["covering_teacher"]["id"], "2026-08-03", 4, coord_headers
    )
    review_coverage(mon["id"], "APPROVE")

    absence = get_absence(ctx["absence"]["id"])
    assert absence["fill_status"] == "COVERED_INTERNALLY"
    assert absence["days_covered_internal"] == 1
    assert absence["days_covered_sub"] == 0
    assert absence["days_uncovered"] == 4
    assert_absence_day_conservation(absence)


def test_day_conservation_restored_by_compensating_cancel(api):
    """PRD 3.6: "cancelling an `APPROVED` one decrements the absence's
    internal-day count, and when that count reaches zero the absence falls
    back from `COVERED_INTERNALLY` to `UNFILLED`, eligible for dispatch
    again."
    PRD 3.6: "The conservation invariant holds at all times: internal days
    plus substitute days plus uncovered days exactly equal `total_days`."

    Design: Difficulty/compensating_invariant/absence_day_coverage_conservation_across_approve_and_cancel
    """
    ctx = unfilled_absence_ctx(
        start_date="2026-08-03", end_date="2026-08-07", run_for_date="2026-08-05"
    )
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])
    mon = propose_coverage(
        ctx["absence"]["id"], ctx["covering_teacher"]["id"], "2026-08-03", 4, coord_headers
    )
    tue = propose_coverage(
        ctx["absence"]["id"], ctx["covering_teacher"]["id"], "2026-08-04", 4, coord_headers
    )
    review_coverage(mon["id"], "APPROVE")
    review_coverage(tue["id"], "APPROVE")

    cancelled = cancel_coverage(mon["id"], coord_headers)
    assert cancelled["status"] == "CANCELLED"

    absence = get_absence(ctx["absence"]["id"])
    assert absence["days_covered_internal"] == 1, "Tuesday's approval remains"
    assert absence["days_covered_sub"] == 0
    assert absence["days_uncovered"] == 4
    assert_absence_day_conservation(absence)
    assert absence["fill_status"] == "COVERED_INTERNALLY", (
        "one approved coverage remains, so the absence does not fall back"
    )

    tue_after = validate_success(
        api.get_internal_coverage(tue["id"], make_district_admin_headers()), 200
    )
    assert tue_after["status"] == "APPROVED"
