"""Prevailing-wage labor costing: classification rates, shift multiplier,
daily vs weekly overtime regimes, and pinned rounding order
(PRD section 3.8)."""
from test_helpers import (
    assert_labor_entry,
    create_labor_entry_payload,
    create_project,
    make_site_supervisor_headers,
    validate_success,
)


def _create_entry(api, project_id, **overrides):
    resp = api.create_labor_entry(
        create_labor_entry_payload(project_id=project_id, **overrides),
        make_site_supervisor_headers("sup-1"),
    )
    return validate_success(resp, 201)


def test_daily_ot_splits_after_eight_hours(api):
    """PRD section 3.8: "Under `DAILY_OT`, the split is per-entry: up to eight
    hours of the entry's `hours_worked` are straight time, and any hours beyond
    eight are overtime."

    Design: Difficulty/dual_variant_calc/labor_daily_vs_weekly_ot_divergence
    """
    project = create_project(name="Daily OT Job", site_address="1 Plant Rd", ot_basis="DAILY_OT")
    entry = _create_entry(
        api, project["id"], worker_ref="U-2001", work_date="2026-08-10", hours_worked=10
    )
    assert_labor_entry(entry)
    assert entry["regular_hours"] == 8, (
        f"DAILY_OT: first 8 hours straight, got {entry['regular_hours']}"
    )
    assert entry["overtime_hours"] == 2, (
        f"DAILY_OT: hours beyond eight are overtime, got {entry['overtime_hours']}"
    )
    # 68000 straight + 25500 overtime + 21000 fringe.
    assert entry["total_cost_cents"] == 114500, (
        f"Expected 114500 total cents, got {entry['total_cost_cents']}"
    )


def test_weekly_ot_no_prior_hours_all_straight(api):
    """PRD section 3.8: "Under `WEEKLY_OT`, the threshold applies to cumulative
    same-worker hours across the ISO week, Monday through Sunday, containing
    the entry's `work_date`: the system first totals the `hours_worked` of the
    worker's other entries in that week whose status is `SUBMITTED`,
    `APPROVED`, or `INVOICED` — entries still `DRAFT` or already `REJECTED` do
    not count."
    PRD section 3.8: "Identical `hours_worked` can therefore split differently
    on a weekly-regime project depending on what the worker has already logged
    that week."

    Design: Difficulty/dual_variant_calc/labor_daily_vs_weekly_ot_divergence
    """
    daily = create_project(name="Daily OT Job", site_address="1 Plant Rd", ot_basis="DAILY_OT")
    weekly = create_project(name="Weekly OT Job", site_address="2 Plant Rd", ot_basis="WEEKLY_OT")

    daily_entry = _create_entry(
        api, daily["id"], worker_ref="U-2001", work_date="2026-08-10", hours_worked=10
    )
    weekly_entry = _create_entry(
        api, weekly["id"], worker_ref="U-2001", work_date="2026-08-10", hours_worked=10
    )

    assert weekly_entry["regular_hours"] == 10
    assert weekly_entry["overtime_hours"] == 0, (
        "No prior weekly hours: the whole 10-hour day fits under the 40-hour threshold"
    )
    # 85000 straight + 0 overtime + 21000 fringe.
    assert weekly_entry["total_cost_cents"] == 106000
    assert daily_entry["total_cost_cents"] == 114500
    assert daily_entry["total_cost_cents"] != weekly_entry["total_cost_cents"], (
        "Identical hours must diverge between the daily and weekly OT regimes"
    )


def test_foreman_night_shift_cost_components(api):
    """PRD section 3.8: "The `base_rate_cents` is looked up from the
    classification: 8,500 cents per hour for `MW_JOURNEYMAN`, 5,600 for
    `MW_APPRENTICE`, 9,800 for `MW_FOREMAN`, and 7,200 for `OPERATOR`. The
    shift multiplier is 1.0 for a `DAY` shift and 1.10 for a `NIGHT` shift."
    PRD section 3.8: "The straight-time component is `regular_hours` times
    `base_rate_cents` times the shift multiplier. The overtime component is
    `overtime_hours` times `base_rate_cents` times one and a half times the
    shift multiplier. The fringe component is `hours_worked` times 2,100 cents
    per hour, applied to every hour worked regardless of the overtime split."

    Design: Difficulty/combinatorial_formula/labor_cost_multi_input_tiered
    """
    project = create_project(name="Night Shift Job", site_address="3 Plant Rd", ot_basis="DAILY_OT")
    entry = _create_entry(
        api,
        project["id"],
        worker_ref="U-3001",
        classification="MW_FOREMAN",
        work_date="2026-08-10",
        hours_worked=9,
        shift="NIGHT",
    )
    assert entry["base_rate_cents"] == 9800
    assert entry["regular_hours"] == 8
    assert entry["overtime_hours"] == 1
    # straight: round_half_up(8 * 9800 * 1.10) = 86240
    # overtime: round_half_up(1 * 9800 * 1.5 * 1.10) = 16170
    # fringe:   9 * 2100 = 18900
    assert entry["total_cost_cents"] == 86240 + 16170 + 18900


def test_foreman_night_total_is_sum_of_rounded_components(api):
    """PRD section 2.8: "Labor costing pins its rounding order: the
    straight-time, overtime, and fringe components are each rounded half-up to
    whole cents individually, and only then summed into the entry's total —
    the components are never summed first and rounded once."
    PRD section 3.8: "Their sum is the entry's `total_cost_cents`."

    Design: Difficulty/combinatorial_formula/labor_cost_multi_input_tiered
    """
    project = create_project(name="Night Shift Job", site_address="3 Plant Rd", ot_basis="DAILY_OT")
    entry = _create_entry(
        api,
        project["id"],
        worker_ref="U-3001",
        classification="MW_FOREMAN",
        work_date="2026-08-10",
        hours_worked=9,
        shift="NIGHT",
    )
    assert entry["total_cost_cents"] == 121310, (
        f"86240 straight + 16170 overtime + 18900 fringe = 121310, got "
        f"{entry['total_cost_cents']}"
    )


def test_exactly_eight_hours_has_zero_overtime(api):
    """PRD section 3.8: "Under `DAILY_OT`, the split is per-entry: up to eight
    hours of the entry's `hours_worked` are straight time, and any hours beyond
    eight are overtime."

    Design: Difficulty/boundary_precision_check/labor_exact_daily_threshold_no_ot
    """
    project = create_project(name="Boundary Job", site_address="13 Plant Rd", ot_basis="DAILY_OT")
    entry = _create_entry(
        api, project["id"], worker_ref="U-8001", work_date="2026-08-10", hours_worked=8
    )
    assert entry["regular_hours"] == 8
    assert entry["overtime_hours"] == 0, (
        "Exactly 8.0 hours is straight time; overtime requires hours beyond eight"
    )


def test_exactly_eight_hours_total_cost(api):
    """PRD section 3.8: "The straight-time component is `regular_hours` times
    `base_rate_cents` times the shift multiplier. The overtime component is
    `overtime_hours` times `base_rate_cents` times one and a half times the
    shift multiplier. The fringe component is `hours_worked` times 2,100 cents
    per hour, applied to every hour worked regardless of the overtime split.
    Their sum is the entry's `total_cost_cents`."

    Design: Difficulty/boundary_precision_check/labor_exact_daily_threshold_no_ot
    """
    project = create_project(name="Boundary Job", site_address="13 Plant Rd", ot_basis="DAILY_OT")
    entry = _create_entry(
        api, project["id"], worker_ref="U-8001", work_date="2026-08-10", hours_worked=8
    )
    # 8 * 8500 = 68000 straight, 0 overtime, 8 * 2100 = 16800 fringe.
    assert entry["total_cost_cents"] == 84800, (
        f"68000 straight + 0 overtime + 16800 fringe = 84800, got "
        f"{entry['total_cost_cents']}"
    )


def test_weekly_ot_accumulation_across_entries(api, sup_headers):
    """PRD section 3.8: "The new entry's straight-time portion is then the
    amount of the forty-hour weekly threshold not already absorbed by that
    prior total: take the smaller of (the prior total plus this entry's hours)
    and forty, subtract the smaller of (the prior total) and forty, and floor
    the result at zero; whatever remains of the entry's hours is overtime."

    Design: Corner/calculations/weekly_ot_accumulation_across_entries
    """
    project = create_project(
        name="Weekly Accumulation Job", site_address="33 Plant Rd", ot_basis="WEEKLY_OT"
    )
    # PRD caps a single entry's hours_worked at 24, so the 38 prior hours are
    # accumulated across two same-week entries (Mon 2026-08-10, Tue 2026-08-11).
    first = _create_entry(
        api, project["id"], worker_ref="U-2001", work_date="2026-08-10", hours_worked=24
    )
    # 24 * 8500 = 204000 straight, 24 * 2100 = 50400 fringe.
    assert first["regular_hours"] == 24
    assert first["overtime_hours"] == 0
    assert first["total_cost_cents"] == 254400

    # The 24 hours count once SUBMITTED (DRAFT entries would not).
    validate_success(api.submit_labor_entry(first["id"], sup_headers))

    second = _create_entry(
        api, project["id"], worker_ref="U-2001", work_date="2026-08-11", hours_worked=14
    )
    # min(24+14, 40) - min(24, 40) = 38 - 24 = 14 straight, 0 overtime.
    assert second["regular_hours"] == 14
    assert second["overtime_hours"] == 0
    # 14*8500 = 119000 straight, 14*2100 = 29400 fringe.
    assert second["total_cost_cents"] == 148400

    validate_success(api.submit_labor_entry(second["id"], sup_headers))

    third = _create_entry(
        api, project["id"], worker_ref="U-2001", work_date="2026-08-12", hours_worked=5
    )
    assert third["regular_hours"] == 2, (
        f"Prior 38h absorbs all but 2h of the 40h threshold, got {third['regular_hours']}"
    )
    assert third["overtime_hours"] == 3
    # 2*8500 = 17000 straight, 3*8500*1.5 = 38250 overtime, 5*2100 = 10500 fringe.
    assert third["total_cost_cents"] == 65750


def test_night_shift_multiplier_without_ot(api):
    """PRD section 3.8: "The `base_rate_cents` is looked up from the
    classification: 8,500 cents per hour for `MW_JOURNEYMAN`, 5,600 for
    `MW_APPRENTICE`, 9,800 for `MW_FOREMAN`, and 7,200 for `OPERATOR`. The
    shift multiplier is 1.0 for a `DAY` shift and 1.10 for a `NIGHT` shift."

    Design: Corner/calculations/night_shift_multiplier_without_ot
    """
    project = create_project(name="Night Rate Job", site_address="34 Plant Rd", ot_basis="DAILY_OT")
    entry = _create_entry(
        api,
        project["id"],
        worker_ref="U-9301",
        classification="MW_APPRENTICE",
        work_date="2026-08-10",
        hours_worked=8,
        shift="NIGHT",
    )
    assert entry["base_rate_cents"] == 5600
    assert entry["overtime_hours"] == 0
    # round_half_up(8 * 5600 * 1.10) = 49280 straight, 8 * 2100 = 16800 fringe.
    assert entry["total_cost_cents"] == 66080, (
        f"49280 straight (night multiplier) + 16800 fringe = 66080, got "
        f"{entry['total_cost_cents']}"
    )
