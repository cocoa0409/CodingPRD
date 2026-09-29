"""Composed arithmetic whose evaluation order the contract pins.

Two published figures in this service are the result of several stacked steps
whose order is not free. A reconciliation report rounds each per-line variance
percentage before revenue-weighting them, and on realistic figures that order is
what decides which side of the materiality threshold the headline number lands
on. The budget optimizer runs the same greedy walk twice and prices the agency
fee out of the first pass only, so the fee that gets published is deliberately
not the one the second pass's smaller churn would imply.
"""

from decimal import Decimal

from test_helpers import (
    assertions,
    constants,
    factories,
    fixtures,
)


def _dec(value) -> Decimal:
    """A JSON number as an exact decimal, so pinned figures compare exactly."""
    return Decimal(str(value))


def _line_for(report, channel_id):
    """The report's variance line naming one channel."""
    matches = [
        line for line in report["variance_lines"] if line["channel_id"] == channel_id
    ]
    assert len(matches) == 1, (
        f"expected exactly one variance line for {channel_id}, got {len(matches)}"
    )
    return matches[0]


def _published_run_with_two_reports(api):
    """A published run and two reports over it, one material and one not.

    The run is fitted in the period-of-effect carryover mode, backtested and
    published, which leaves the market's posture out of FROZEN and the run's
    calibration untouched, so both reports are admissible and both compare
    against the uncalibrated revenue figures.
    """
    ctx = fixtures.published_run(api)
    ctx["material_report"] = fixtures.file_reconciliation_report(api, ctx)
    ctx["immaterial_report"] = fixtures.file_reconciliation_report(
        api,
        ctx,
        a_search_platform_cents=factories.PLATFORM_A_SEARCH_IMMATERIAL_CENTS,
        b_social_platform_cents=factories.PLATFORM_B_SOCIAL_IMMATERIAL_CENTS,
        reporting_period_start=fixtures.F1_IMMATERIAL_PERIOD_START,
        reporting_period_end=fixtures.F1_IMMATERIAL_PERIOD_END,
    )
    return ctx


def test_per_line_variance_percentage_is_rounded_at_the_line(api):
    """PRD 3.9: "For each line, the model figure described above becomes that line's `model_cents`; `variance_cents` is the line's `platform_revenue_cents` minus its `model_cents`, so a platform claiming more than the model gives a positive variance; and `variance_pct` is one hundred multiplied by `variance_cents`, divided by `model_cents`, **rounded half-up to two decimal places at this point**."
    PRD 3.9: "The resulting objects are stored on the report as `variance_lines`, each carrying `channel_id`, `model_cents`, `platform_revenue_cents`, `variance_cents` and `variance_pct`, in that ascending channel order."

    Design: Difficulty/combinatorial_formula/reconciliation_rounding_order_flips_materiality
    """
    ctx = _published_run_with_two_reports(api)
    report = ctx["material_report"]
    a_search = ctx["a_search"]["id"]
    b_social = ctx["b_social"]["id"]

    assert [line["channel_id"] for line in report["variance_lines"]] == [
        a_search,
        b_social,
    ], (
        "variance_lines should run in ascending channel_code order, A_SEARCH then "
        f"B_SOCIAL, got {[line['channel_id'] for line in report['variance_lines']]}"
    )

    a_line = _line_for(report, a_search)
    b_line = _line_for(report, b_social)

    assert a_line["model_cents"] == fixtures.F1_EFFECT_REVENUE_A_SEARCH, (
        f"A_SEARCH model_cents should be {fixtures.F1_EFFECT_REVENUE_A_SEARCH}, got "
        f"{a_line['model_cents']}"
    )
    assert (
        a_line["platform_revenue_cents"]
        == factories.PLATFORM_A_SEARCH_MATERIAL_CENTS
    ), f"got {a_line['platform_revenue_cents']}"
    assert a_line["variance_cents"] == fixtures.F1_RAW_VARIANCE_A_SEARCH_CENTS, (
        f"A_SEARCH variance_cents should be "
        f"{fixtures.F1_RAW_VARIANCE_A_SEARCH_CENTS}, got {a_line['variance_cents']}"
    )
    assert _dec(a_line["variance_pct"]) == _dec(
        fixtures.F1_RAW_VARIANCE_A_SEARCH_PCT
    ), (
        f"A_SEARCH variance_pct should be rounded to "
        f"{fixtures.F1_RAW_VARIANCE_A_SEARCH_PCT} at the line, got "
        f"{a_line['variance_pct']}"
    )

    assert b_line["model_cents"] == fixtures.F1_EFFECT_REVENUE_B_SOCIAL, (
        f"B_SOCIAL model_cents should be {fixtures.F1_EFFECT_REVENUE_B_SOCIAL}, got "
        f"{b_line['model_cents']}"
    )
    assert (
        b_line["platform_revenue_cents"]
        == factories.PLATFORM_B_SOCIAL_MATERIAL_CENTS
    ), f"got {b_line['platform_revenue_cents']}"
    assert b_line["variance_cents"] == fixtures.F1_RAW_VARIANCE_B_SOCIAL_CENTS, (
        f"B_SOCIAL variance_cents should be "
        f"{fixtures.F1_RAW_VARIANCE_B_SOCIAL_CENTS}, got {b_line['variance_cents']}"
    )
    assert _dec(b_line["variance_pct"]) == _dec(
        fixtures.F1_RAW_VARIANCE_B_SOCIAL_PCT
    ), (
        f"B_SOCIAL variance_pct should be rounded to "
        f"{fixtures.F1_RAW_VARIANCE_B_SOCIAL_PCT} at the line, got "
        f"{b_line['variance_pct']}"
    )

    for line in report["variance_lines"]:
        assertions.assert_decimal_places(line["variance_pct"], 2, "variance_pct")


def test_weighted_variance_of_rounded_lines_flags_the_report_material(api):
    """PRD 3.9: "The headline number, `weighted_variance_pct`, is a revenue-weighted mean of the **already-rounded** per-line percentages: the sum, across lines, of each line's `variance_pct` multiplied by that line's `model_cents`, divided by `model_attributed_revenue_cents`, rounded half-up to two decimal places."
    PRD 3.9: "This order is mandated and the alternative — weighting the unrounded percentages and rounding once at the end — is explicitly rejected."
    PRD 3.9: "That flag, `attribution_gap_flag`, is `MATERIAL` when the absolute value of `weighted_variance_pct` is at least 15.00 and `IMMATERIAL` when it is strictly below 15.00."

    Design: Difficulty/combinatorial_formula/reconciliation_rounding_order_flips_materiality
    """
    ctx = _published_run_with_two_reports(api)
    report = ctx["material_report"]

    assert _dec(report["weighted_variance_pct"]) == _dec(
        fixtures.F1_RAW_WEIGHTED_VARIANCE_PCT
    ), (
        "weighting the already-rounded line percentages should give "
        f"{fixtures.F1_RAW_WEIGHTED_VARIANCE_PCT}, got "
        f"{report['weighted_variance_pct']}"
    )
    # Weighting the unrounded percentages first and rounding once at the end
    # lands a hundredth of a point lower, which is the rejected order.
    assert _dec(report["weighted_variance_pct"]) != _dec(
        fixtures.F1_FORBIDDEN_WEIGHTED_VARIANCE_PCT
    ), (
        f"{fixtures.F1_FORBIDDEN_WEIGHTED_VARIANCE_PCT} is what the rejected order "
        "produces on these figures"
    )

    # The figures sit exactly on the threshold, so that single hundredth of a
    # point is what decides the flag stakeholders read.
    assert _dec(report["weighted_variance_pct"]) >= _dec(constants.MATERIALITY_PCT), (
        f"{report['weighted_variance_pct']} should be at or above "
        f"{constants.MATERIALITY_PCT}"
    )
    assert report["attribution_gap_flag"] == "MATERIAL", (
        "a weighted gap at the threshold is MATERIAL, got "
        f"{report['attribution_gap_flag']}"
    )
    assert _dec(fixtures.F1_FORBIDDEN_WEIGHTED_VARIANCE_PCT) < _dec(
        constants.MATERIALITY_PCT
    ), "the rejected order would have fallen below the threshold"


def test_second_report_stays_immaterial_under_the_mandated_order(api):
    """PRD 3.9: "The headline number, `weighted_variance_pct`, is a revenue-weighted mean of the **already-rounded** per-line percentages: the sum, across lines, of each line's `variance_pct` multiplied by that line's `model_cents`, divided by `model_attributed_revenue_cents`, rounded half-up to two decimal places."
    PRD 3.9: "That flag, `attribution_gap_flag`, is `MATERIAL` when the absolute value of `weighted_variance_pct` is at least 15.00 and `IMMATERIAL` when it is strictly below 15.00."
    PRD 3.9: "For each line, the model figure described above becomes that line's `model_cents`; `variance_cents` is the line's `platform_revenue_cents` minus its `model_cents`, so a platform claiming more than the model gives a positive variance; and `variance_pct` is one hundred multiplied by `variance_cents`, divided by `model_cents`, **rounded half-up to two decimal places at this point**."

    Design: Difficulty/combinatorial_formula/reconciliation_rounding_order_flips_materiality
    """
    ctx = _published_run_with_two_reports(api)
    report = ctx["immaterial_report"]
    a_line = _line_for(report, ctx["a_search"]["id"])
    b_line = _line_for(report, ctx["b_social"]["id"])

    assert a_line["variance_cents"] == fixtures.F1_IMMATERIAL_VARIANCE_A_SEARCH_CENTS, (
        f"A_SEARCH variance_cents should be "
        f"{fixtures.F1_IMMATERIAL_VARIANCE_A_SEARCH_CENTS}, got "
        f"{a_line['variance_cents']}"
    )
    assert _dec(a_line["variance_pct"]) == _dec(
        fixtures.F1_IMMATERIAL_VARIANCE_A_SEARCH_PCT
    ), f"got {a_line['variance_pct']}"
    assert b_line["variance_cents"] == fixtures.F1_IMMATERIAL_VARIANCE_B_SOCIAL_CENTS, (
        "a platform claiming less than the model should give a negative variance of "
        f"{fixtures.F1_IMMATERIAL_VARIANCE_B_SOCIAL_CENTS}, got "
        f"{b_line['variance_cents']}"
    )
    assert _dec(b_line["variance_pct"]) == _dec(
        fixtures.F1_IMMATERIAL_VARIANCE_B_SOCIAL_PCT
    ), f"got {b_line['variance_pct']}"

    assert report["total_variance_cents"] == fixtures.F1_IMMATERIAL_TOTAL_VARIANCE_CENTS, (
        f"total_variance_cents should be "
        f"{fixtures.F1_IMMATERIAL_TOTAL_VARIANCE_CENTS}, got "
        f"{report['total_variance_cents']}"
    )
    assert _dec(report["weighted_variance_pct"]) == _dec(
        fixtures.F1_IMMATERIAL_WEIGHTED_VARIANCE_PCT
    ), (
        "weighting the already-rounded line percentages should give "
        f"{fixtures.F1_IMMATERIAL_WEIGHTED_VARIANCE_PCT}, got "
        f"{report['weighted_variance_pct']}"
    )
    assert _dec(report["weighted_variance_pct"]) != _dec(
        fixtures.F1_FORBIDDEN_IMMATERIAL_WEIGHTED_PCT
    ), (
        f"{fixtures.F1_FORBIDDEN_IMMATERIAL_WEIGHTED_PCT} is what the rejected order "
        "produces on these figures"
    )
    assert abs(_dec(report["weighted_variance_pct"])) < _dec(
        constants.MATERIALITY_PCT
    ), f"got {report['weighted_variance_pct']}"
    assert report["attribution_gap_flag"] == "IMMATERIAL", (
        f"got {report['attribution_gap_flag']}"
    )


def test_report_totals_are_exact_integer_sums_on_the_raw_basis(api):
    """PRD 3.9: "Three totals are then summed across the lines: `platform_reported_revenue_cents` from the platform figures, `model_attributed_revenue_cents` from the model figures, and `total_variance_cents` from the per-line variances. All three are exact integer cent arithmetic with no rounding step at all."
    PRD 3.9: "When the run's `calibration_status` is `CALIBRATED` the `basis` is `CALIBRATED` and each channel's model figure is its `calibrated_contribution_revenue_cents`; in every other admissible case the `basis` is `RAW` and the model figure is its `contribution_revenue_cents`."
    PRD 3.9: "A new report is created in `status` `CURRENT`."

    Design: Difficulty/combinatorial_formula/reconciliation_rounding_order_flips_materiality
    """
    ctx = _published_run_with_two_reports(api)
    material = ctx["material_report"]
    immaterial = ctx["immaterial_report"]

    for label, report in (("material", material), ("immaterial", immaterial)):
        assert report["basis"] == "RAW", (
            f"the {label} report is filed against an uncalibrated run, so its basis "
            f"should be RAW, got {report['basis']}"
        )
        assert report["status"] == "CURRENT", (
            f"the {label} report should be created CURRENT, got {report['status']}"
        )
        assert (
            report["model_attributed_revenue_cents"]
            == fixtures.F1_RAW_MODEL_ATTRIBUTED_CENTS
        ), (
            f"the {label} report should attribute "
            f"{fixtures.F1_RAW_MODEL_ATTRIBUTED_CENTS} to the model, got "
            f"{report['model_attributed_revenue_cents']}"
        )
        assertions.assert_reconciliation_report(report)

    assert (
        material["platform_reported_revenue_cents"]
        == fixtures.F1_RAW_PLATFORM_REPORTED_CENTS
    ), (
        f"platform_reported_revenue_cents should be "
        f"{fixtures.F1_RAW_PLATFORM_REPORTED_CENTS}, got "
        f"{material['platform_reported_revenue_cents']}"
    )
    assert material["total_variance_cents"] == fixtures.F1_RAW_TOTAL_VARIANCE_CENTS, (
        f"total_variance_cents should be {fixtures.F1_RAW_TOTAL_VARIANCE_CENTS}, got "
        f"{material['total_variance_cents']}"
    )


def test_reallocation_fee_stays_pinned_at_the_first_pass_churn(api):
    """PRD 3.8: "The pass-one churn is the sum, across channels, of the absolute difference between each channel's pass-one allocation and its `baseline_spend_cents`, and `reallocation_fee_cents` is that churn multiplied by `reallocation_fee_pct`, divided by one hundred, rounded half-up to a whole cent."
    PRD 3.8: "Pass two then runs the greedy walk again over `total_budget_cents` reduced by that fee."
    PRD 3.8: "Critically, the fee is **pinned at its pass-one value** and is not recomputed from pass two's smaller churn: the fee prices the plan the optimizer first proposed, and recomputing it would make the two passes chase each other without converging."

    Design: Difficulty/combinatorial_formula/budget_fee_pinned_across_two_pass_optimization
    """
    ctx = fixtures.optimized_scenario(api)
    scenario = ctx["scenario"]

    assert scenario["status"] == "OPTIMIZED", f"got {scenario['status']}"
    assert scenario["reallocation_fee_cents"] == fixtures.F1_REALLOCATION_FEE_CENTS, (
        "the fee should price the first pass's churn of "
        f"{fixtures.F1_PASS1_CHURN_CENTS} cents, giving "
        f"{fixtures.F1_REALLOCATION_FEE_CENTS}, got "
        f"{scenario['reallocation_fee_cents']}"
    )

    # The published churn is the second pass's, which is smaller; pricing it
    # would have produced a different fee, and that fee must not appear.
    assert scenario["shifted_total_cents"] == fixtures.F1_SHIFTED_TOTAL_CENTS, (
        f"shifted_total_cents should be {fixtures.F1_SHIFTED_TOTAL_CENTS}, got "
        f"{scenario['shifted_total_cents']}"
    )
    assert scenario["shifted_total_cents"] != fixtures.F1_PASS1_CHURN_CENTS, (
        "the second pass churns less than the first, which is exactly why the fee "
        "cannot be recomputed from it"
    )
    assert (
        scenario["reallocation_fee_cents"]
        != fixtures.F1_FORBIDDEN_RECOMPUTED_FEE_CENTS
    ), (
        f"{fixtures.F1_FORBIDDEN_RECOMPUTED_FEE_CENTS} is the fee a recomputation "
        "from the second pass would have produced"
    )
    fee_from_second_pass = (
        _dec(scenario["shifted_total_cents"])
        * _dec(scenario["reallocation_fee_pct"])
        / Decimal("100")
    )
    assert _dec(scenario["reallocation_fee_cents"]) != fee_from_second_pass, (
        "the published fee must not be the second pass's churn priced at "
        f"{scenario['reallocation_fee_pct']} percent"
    )


def test_pass_two_allocations_conserve_the_whole_budget(api):
    """PRD 3.8: "Each allocation row's `allocated_cents` becomes its pass-two figure; its `shifted_cents` becomes the absolute difference between that figure and its `baseline_spend_cents`; its `constraint_binding` becomes `FLOOR` when `allocated_cents` equals the channel's `min_spend_cents`, `CEILING` when it equals the channel's `max_spend_cents`, and `NONE` otherwise, with `FLOOR` winning when a channel's floor and ceiling are the same number; and its `projected_contribution_units` becomes the projection function evaluated at `allocated_cents`, rounded half-up to four decimal places."
    PRD 3.8: "On the scenario, `allocated_total_cents` is the sum of the rows' `allocated_cents`; `shifted_total_cents` is the sum of the rows' `shifted_cents`, which is the pass-two churn and is reporting only; `unallocated_cents` is `total_budget_cents` minus `reallocation_fee_cents` minus `allocated_total_cents`; `projected_contribution_units` is the sum of the rows' `projected_contribution_units`; and `projected_incremental_revenue_cents` is that total multiplied by the referenced run's `unit_price_cents`, rounded half-up to a whole cent."
    PRD 3.8: "`planning_period_count` is derived as the length of the horizon divided by the period length of the referenced run's data window — seven days per period for a `WEEKLY` window, one day per period for a `DAILY` one — and that division must come out exact, or the create is `ERR_INVALID_REQUEST`."

    Design: Difficulty/combinatorial_formula/budget_fee_pinned_across_two_pass_optimization
    """
    ctx = fixtures.optimized_scenario(api)
    scenario = ctx["scenario"]
    rows = assertions.rows_by(ctx["allocations"], "channel_id")
    a_row = rows[ctx["a_search"]["id"]]
    b_row = rows[ctx["b_social"]["id"]]

    assert scenario["planning_period_count"] == fixtures.F1_PLANNING_PERIOD_COUNT, (
        f"planning_period_count should be {fixtures.F1_PLANNING_PERIOD_COUNT}, got "
        f"{scenario['planning_period_count']}"
    )

    assert a_row["allocated_cents"] == fixtures.F1_ALLOCATED_A_SEARCH_CENTS, (
        f"A_SEARCH allocated_cents should be "
        f"{fixtures.F1_ALLOCATED_A_SEARCH_CENTS}, got {a_row['allocated_cents']}"
    )
    assert a_row["shifted_cents"] == fixtures.F1_SHIFTED_A_SEARCH_CENTS, (
        f"A_SEARCH shifted_cents should be {fixtures.F1_SHIFTED_A_SEARCH_CENTS}, got "
        f"{a_row['shifted_cents']}"
    )
    assert b_row["allocated_cents"] == fixtures.F1_ALLOCATED_B_SOCIAL_CENTS, (
        f"B_SOCIAL allocated_cents should be "
        f"{fixtures.F1_ALLOCATED_B_SOCIAL_CENTS}, got {b_row['allocated_cents']}"
    )
    assert b_row["shifted_cents"] == fixtures.F1_SHIFTED_B_SOCIAL_CENTS, (
        f"B_SOCIAL shifted_cents should be {fixtures.F1_SHIFTED_B_SOCIAL_CENTS}, got "
        f"{b_row['shifted_cents']}"
    )
    for label, row in (("A_SEARCH", a_row), ("B_SOCIAL", b_row)):
        assert row["constraint_binding"] == "NONE", (
            f"{label} sits between its floor and its ceiling, so its "
            f"constraint_binding should be NONE, got {row['constraint_binding']}"
        )

    assert scenario["allocated_total_cents"] == fixtures.F1_ALLOCATED_TOTAL_CENTS, (
        f"allocated_total_cents should be {fixtures.F1_ALLOCATED_TOTAL_CENTS}, got "
        f"{scenario['allocated_total_cents']}"
    )
    assert scenario["unallocated_cents"] == fixtures.F1_UNALLOCATED_CENTS, (
        f"unallocated_cents should be {fixtures.F1_UNALLOCATED_CENTS}, got "
        f"{scenario['unallocated_cents']}"
    )
    assertions.assert_budget_conservation(scenario)


def test_projections_follow_the_fee_reduced_second_pass(api):
    """PRD 3.8: "For a channel and a candidate horizon-level allocation, the per-period allocation is the candidate amount divided by `planning_period_count`; the projected units for the horizon are `planning_period_count` multiplied by the channel's `response_ceiling_units`, multiplied by that per-period allocation, divided by the sum of that per-period allocation and the channel's `saturation_half_point_cents`."
    PRD 3.8: "Pass two's result is what gets published."
    PRD 3.8: "On the scenario, `allocated_total_cents` is the sum of the rows' `allocated_cents`; `shifted_total_cents` is the sum of the rows' `shifted_cents`, which is the pass-two churn and is reporting only; `unallocated_cents` is `total_budget_cents` minus `reallocation_fee_cents` minus `allocated_total_cents`; `projected_contribution_units` is the sum of the rows' `projected_contribution_units`; and `projected_incremental_revenue_cents` is that total multiplied by the referenced run's `unit_price_cents`, rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/budget_fee_pinned_across_two_pass_optimization
    """
    ctx = fixtures.optimized_scenario(api)
    scenario = ctx["scenario"]
    rows = assertions.rows_by(ctx["allocations"], "channel_id")
    a_row = rows[ctx["a_search"]["id"]]
    b_row = rows[ctx["b_social"]["id"]]

    assert _dec(a_row["projected_contribution_units"]) == _dec(
        fixtures.F1_PROJECTED_UNITS_A_SEARCH
    ), (
        "A_SEARCH's projection is evaluated at its pass-two allocation of "
        f"{fixtures.F1_ALLOCATED_A_SEARCH_CENTS} cents, giving "
        f"{fixtures.F1_PROJECTED_UNITS_A_SEARCH}, got "
        f"{a_row['projected_contribution_units']}"
    )
    assert _dec(b_row["projected_contribution_units"]) == _dec(
        fixtures.F1_PROJECTED_UNITS_B_SOCIAL
    ), (
        f"B_SOCIAL's projection should be {fixtures.F1_PROJECTED_UNITS_B_SOCIAL}, got "
        f"{b_row['projected_contribution_units']}"
    )
    for label, row in (("A_SEARCH", a_row), ("B_SOCIAL", b_row)):
        assertions.assert_decimal_places(
            row["projected_contribution_units"],
            4,
            f"{label} projected_contribution_units",
        )

    assert _dec(scenario["projected_contribution_units"]) == _dec(
        fixtures.F1_PROJECTED_UNITS_TOTAL
    ), (
        "the scenario total should be the sum of the rows, "
        f"{fixtures.F1_PROJECTED_UNITS_TOTAL}, got "
        f"{scenario['projected_contribution_units']}"
    )
    assert (
        scenario["projected_incremental_revenue_cents"]
        == fixtures.F1_PROJECTED_REVENUE_CENTS
    ), (
        "the projected total priced at the run's unit price should be "
        f"{fixtures.F1_PROJECTED_REVENUE_CENTS}, got "
        f"{scenario['projected_incremental_revenue_cents']}"
    )


def test_greedy_awards_whole_steps_and_strands_the_short_remainder(api):
    """PRD 3.8: "Each channel is seeded at its own `min_spend_cents`."
    PRD 3.8: "Then, while the remaining budget is at least one hundred thousand cents — a one-thousand-unit-of-currency marginal step — the walk forms a candidate set of the channels for which adding one more step would keep the allocation at or below the channel's `max_spend_cents`."
    PRD 3.8: "Otherwise it selects the candidate for which the projected-units gain from adding one step is largest, breaking ties by ascending `channel_code` and never by identifier or creation time, awards that channel one step, and reduces the remaining budget by one step."

    Design: Difficulty/combinatorial_formula/budget_fee_pinned_across_two_pass_optimization
    """
    ctx = fixtures.optimized_scenario(api)
    scenario = ctx["scenario"]

    for row in ctx["allocations"]:
        assert row["allocated_cents"] % constants.MARGINAL_STEP_CENTS == 0, (
            "a walk seeded on round floors and advancing in "
            f"{constants.MARGINAL_STEP_CENTS}-cent steps cannot leave "
            f"{row['allocated_cents']} on a channel"
        )
        assert row["shifted_cents"] == abs(
            row["allocated_cents"] - row["baseline_spend_cents"]
        ), (
            f"shifted_cents {row['shifted_cents']} should be the distance between "
            f"the published {row['allocated_cents']} and the baseline "
            f"{row['baseline_spend_cents']}"
        )

    # The fee is carved out of the second pass's budget, so the walk runs short
    # of a whole step and what is left over is stranded rather than awarded.
    assert scenario["unallocated_cents"] == fixtures.F1_UNALLOCATED_CENTS, (
        f"unallocated_cents should be {fixtures.F1_UNALLOCATED_CENTS}, got "
        f"{scenario['unallocated_cents']}"
    )
    assert 0 < scenario["unallocated_cents"] < constants.MARGINAL_STEP_CENTS, (
        f"{scenario['unallocated_cents']} cents is left over, which must be a "
        f"positive amount short of one {constants.MARGINAL_STEP_CENTS}-cent step"
    )
    assert scenario["reallocation_fee_cents"] == fixtures.F1_REALLOCATION_FEE_CENTS, (
        "the stranded remainder only makes sense against the pinned fee of "
        f"{fixtures.F1_REALLOCATION_FEE_CENTS}, got "
        f"{scenario['reallocation_fee_cents']}"
    )
