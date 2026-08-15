"""Fill-rate analytics: the SUB_ONLY and ANY_COVERAGE variants side by side,
and the zero-denominator null-rate rule."""
from test_helpers import (
    accept_offer,
    basic_world,
    cancel_absence_ok,
    get_absence,
    make_coordinator_headers,
    make_staff,
    make_teacher_headers,
    offer_assignment,
    onboard_substitute,
    propose_coverage,
    report_absence,
    review_coverage,
    run_dispatch_batch,
    validate_success,
)


def _fill_rate_rows(api, district_admin_headers, school_id, from_date, to_date):
    data = validate_success(
        api.get_fill_rate(
            district_admin_headers,
            params={"from_date": from_date, "to_date": to_date, "school_id": school_id},
        ),
        200,
    )
    return {row["day_of_week"]: row for row in data["rows"]}


def _variant_divergence_ctx():
    """Absence A1 Mon 2026-08-03 (MATH) filled by sub A; absence A2 Tue
    2026-08-04 (SCIENCE, empty pool) driven UNFILLED then COVERED_INTERNALLY;
    absence A3 Wed 2026-08-05 cancelled."""
    ctx = basic_world()
    teacher2 = make_staff(
        ctx["school"]["id"], full_name="Teach Two", subject="SCIENCE", grade_band="HIGH"
    )
    ctx["teacher2"] = teacher2
    ctx["sub"] = onboard_substitute()
    coord_headers = make_coordinator_headers(ctx["coordinator"]["id"])

    abs1 = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    offer = offer_assignment(abs1["id"], ctx["sub"]["id"], coord_headers)
    accept_offer(offer["id"], ctx["sub"]["id"])

    abs2 = report_absence(
        teacher2, start_date="2026-08-04", end_date="2026-08-04",
        required_subject="SCIENCE",
    )
    abs3 = report_absence(
        ctx["teacher"], start_date="2026-08-05", end_date="2026-08-05",
        absence_type="PERSONAL",
    )
    cancel_absence_ok(abs3["id"], make_teacher_headers(ctx["teacher"]["id"]))

    run_dispatch_batch(ctx["district"]["id"], run_for_date="2026-08-04")
    assert get_absence(abs2["id"])["fill_status"] == "UNFILLED"

    coverage = propose_coverage(abs2["id"], teacher2["id"], "2026-08-04", 3, coord_headers)
    review_coverage(coverage["id"], "APPROVE")
    assert get_absence(abs2["id"])["fill_status"] == "COVERED_INTERNALLY"

    ctx.update({"abs1": abs1, "abs2": abs2, "abs3": abs3})
    return ctx


def test_fill_rate_sub_only_vs_any_coverage_divergence(api, district_admin_headers):
    """PRD 3.8: "The default `SUB_ONLY` variant counts an absence as filled if
    it ever reached `ASSIGNED` — that is, its `fill_status` stands at
    `ASSIGNED`, `COMPLETED`, or `CLOSED`. The `ANY_COVERAGE` variant widens
    filled to also include absences standing at `COVERED_INTERNALLY`."
    PRD 3.8: "The population is absences whose `start_date` falls in the
    range, grouped by school and by the ISO day-of-week of the start date (1
    for Monday through 7 for Sunday)."

    Design: Difficulty/dual_variant_calc/fill_rate_sub_only_vs_any_coverage
    """
    ctx = _variant_divergence_ctx()
    rows = _fill_rate_rows(
        api, district_admin_headers, ctx["school"]["id"], "2026-08-03", "2026-08-09"
    )

    monday = rows[1]
    assert monday["school_id"] == ctx["school"]["id"]
    assert monday["reported_count"] == 1
    assert monday["sub_only_filled_count"] == 1
    assert monday["sub_only_fill_rate"] == 1.0
    assert monday["any_coverage_filled_count"] == 1
    assert monday["any_coverage_fill_rate"] == 1.0

    tuesday = rows[2]
    assert tuesday["reported_count"] == 1
    assert tuesday["sub_only_filled_count"] == 0
    assert tuesday["sub_only_fill_rate"] == 0.0, (
        "internally covered only: unfilled under SUB_ONLY"
    )
    assert tuesday["any_coverage_filled_count"] == 1
    assert tuesday["any_coverage_fill_rate"] == 1.0, (
        "the same absence counts as filled under ANY_COVERAGE"
    )


def test_fill_rate_cancelled_absence_groups_but_not_counted(api, district_admin_headers):
    """PRD 3.8: "Each returned row carries `school_id`, `day_of_week`,
    `reported_count`, `sub_only_filled_count`, `sub_only_fill_rate`,
    `any_coverage_filled_count`, and `any_coverage_fill_rate`; a row exists
    for every school-and-weekday group containing at least one absence in
    range, cancelled ones included in the grouping, though `reported_count`
    and both denominators count only non-`CANCELLED` absences."
    PRD 3.8: "A rate is the filled count divided by that denominator, rounded
    to four decimal places round half up — and when a group's denominator is
    zero, its rate is null rather than zero, and never an error."

    Design: Difficulty/dual_variant_calc/fill_rate_sub_only_vs_any_coverage
    """
    ctx = _variant_divergence_ctx()
    rows = _fill_rate_rows(
        api, district_admin_headers, ctx["school"]["id"], "2026-08-03", "2026-08-09"
    )
    assert set(rows.keys()) == {1, 2, 3}

    wednesday = rows[3]
    assert wednesday["reported_count"] == 0, (
        "the cancelled absence is excluded from the denominator"
    )
    assert wednesday["sub_only_fill_rate"] is None
    assert wednesday["any_coverage_fill_rate"] is None


def test_fill_rate_zero_denominator_row_present_with_zero_count(api, district_admin_headers):
    """PRD 3.8: "Each returned row carries `school_id`, `day_of_week`,
    `reported_count`, `sub_only_filled_count`, `sub_only_fill_rate`,
    `any_coverage_filled_count`, and `any_coverage_fill_rate`; a row exists
    for every school-and-weekday group containing at least one absence in
    range, cancelled ones included in the grouping, though `reported_count`
    and both denominators count only non-`CANCELLED` absences."

    Design: Difficulty/boundary_precision_check/fill_rate_zero_denominator_returns_null
    """
    ctx = basic_world(with_coordinator=False)
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    cancel_absence_ok(absence["id"], make_teacher_headers(ctx["teacher"]["id"]))

    rows = _fill_rate_rows(
        api, district_admin_headers, ctx["school"]["id"], "2026-08-03", "2026-08-09"
    )
    assert set(rows.keys()) == {1}, (
        "exactly one row: the cancelled absence's (school, Monday) group"
    )
    monday = rows[1]
    assert monday["school_id"] == ctx["school"]["id"]
    assert monday["reported_count"] == 0
    assert monday["sub_only_filled_count"] == 0
    assert monday["any_coverage_filled_count"] == 0


def test_fill_rate_zero_denominator_returns_null_not_zero(api, district_admin_headers):
    """PRD 3.8: "A rate is the filled count divided by that denominator,
    rounded to four decimal places round half up — and when a group's
    denominator is zero, its rate is null rather than zero, and never an
    error."

    Design: Difficulty/boundary_precision_check/fill_rate_zero_denominator_returns_null
    """
    ctx = basic_world(with_coordinator=False)
    absence = report_absence(ctx["teacher"], start_date="2026-08-03", end_date="2026-08-03")
    cancel_absence_ok(absence["id"], make_teacher_headers(ctx["teacher"]["id"]))

    rows = _fill_rate_rows(
        api, district_admin_headers, ctx["school"]["id"], "2026-08-03", "2026-08-09"
    )
    monday = rows[1]
    assert monday["sub_only_fill_rate"] is None, "0/0 -> null, not 0.0"
    assert monday["any_coverage_fill_rate"] is None
