"""Two declared variant switches, each pinned on both of its branches.

The contract offers exactly two places where a client chooses between two
genuinely different pieces of arithmetic over identical inputs: a model run's
`carryover_attribution_mode`, which decides whether adstock carryover is credited
to the period the effect lands in or to the period that spent the money, and an
experiment's `readout_method`, which decides whether the lift estimator
differences the control arm's own drift away or rescales the control rate by a
pre-period weight. Both branches of both switches are exercised here over
byte-identical inputs, so every divergence is attributable to the switch alone.
"""

from decimal import Decimal

from test_helpers import (
    assertions,
    factories,
    fixtures,
    test_users,
    validate_success,
)


def _dec(value) -> Decimal:
    """A JSON number as an exact decimal, so pinned figures compare exactly."""
    return Decimal(str(value))


def _both_carryover_variants(api):
    """Two runs over one sealed window, differing only in the carryover mode.

    The window, its two channels, its four sales periods and its eight spend
    rows are built once; the two runs then read the same sealed history, name the
    same two channels and declare the same controls, holdout and seasonality.
    """
    ctx = fixtures.sealed_window(api)
    variants = {}
    for mode in ("EFFECT_PERIOD", "SPEND_PERIOD"):
        run = fixtures.create_run(api, ctx, carryover_attribution_mode=mode)
        run = validate_success(api.fit_model_run(run["id"], test_users.MODELER))
        rows = fixtures.contributions_of(api, run["id"])
        assert len(rows) == 2, f"a two-channel fit writes two rows, got {len(rows)}"
        variants[mode] = {
            "run": run,
            "rows": assertions.rows_by(rows, "channel_id"),
            "listed": rows,
        }
    ctx["variants"] = variants
    return ctx


def _both_readout_variants(api):
    """Two audience-split experiments read out from identical observed counts.

    They sit on different channels of one market so that neither occupies the
    other's channel-window interval, and both are carried through lock, start and
    read-out with the same four conversion counts and the same arm sizes.
    """
    ctx = fixtures.market_with_channels(api)
    drafts = {
        "DIFF_IN_DIFF": fixtures.create_experiment(
            api,
            ctx,
            channel_id=ctx["a_search"]["id"],
            readout_method="DIFF_IN_DIFF",
        ),
        "SYNTHETIC_CONTROL": fixtures.create_experiment(
            api,
            ctx,
            channel_id=ctx["b_social"]["id"],
            readout_method="SYNTHETIC_CONTROL",
        ),
    }
    locked = {
        method: fixtures.locked_experiment(api, ctx, experiment=draft)
        for method, draft in drafts.items()
    }
    fixtures.set_clock(api, fixtures.CLOCK_EXPERIMENT_STARTED)
    running = {
        method: validate_success(
            api.start_experiment(row["id"], test_users.EXPERIMENT_DESIGNER)
        )
        for method, row in locked.items()
    }
    fixtures.set_clock(api, fixtures.CLOCK_EXPERIMENT_ELAPSED)
    read_out = {
        method: validate_success(
            api.read_out_experiment(
                row["id"],
                factories.read_out_payload(),
                test_users.EXPERIMENT_DESIGNER,
            )
        )
        for method, row in running.items()
    }
    ctx["experiments"] = read_out
    return ctx


def test_carryover_mode_diverges_contribution_units_non_monotonically(api):
    """PRD 3.4: "The fourth field is not declarative at all: `carryover_attribution_mode` selects which of two genuinely different decompositions the fit will use, must be stated explicitly on creation, and must be either `EFFECT_PERIOD` or `SPEND_PERIOD` (`EFFECT_PERIOD` is its declared default value)."
    PRD 3.4: "The channel's `contribution_units` is then the exact sum of those per-period values across the whole window, rounded half-up to four decimal places **once**, over the exact sum."
    PRD 3.4: "`baseline_sales_units` is `modeled_sales_units` minus the sum of every included channel's `contribution_units`, rounded half-up to four decimal places, so that the channel contributions plus the baseline reconstruct the modelled sales total exactly."

    Design: Difficulty/dual_variant_calc/carryover_mode_variant_divergence_on_channel_contribution
    """
    ctx = _both_carryover_variants(api)
    a_search = ctx["a_search"]["id"]
    b_social = ctx["b_social"]["id"]
    effect = ctx["variants"]["EFFECT_PERIOD"]
    spend = ctx["variants"]["SPEND_PERIOD"]

    for mode, variant in ctx["variants"].items():
        run = variant["run"]
        assert run["fit_status"] == "FITTED", f"{mode} run did not reach FITTED"
        assert run["modeled_sales_units"] == fixtures.F1_MODELED_SALES_UNITS, (
            f"{mode} modeled_sales_units {run['modeled_sales_units']} should be "
            f"{fixtures.F1_MODELED_SALES_UNITS}, which no carryover mode may move"
        )
        assert run["unit_price_cents"] == fixtures.F1_UNIT_PRICE_CENTS, (
            f"{mode} unit_price_cents {run['unit_price_cents']} should be "
            f"{fixtures.F1_UNIT_PRICE_CENTS}"
        )
        assert (
            run["observation_period_count"] == fixtures.F1_OBSERVATION_PERIOD_COUNT
        ), f"{mode} observation_period_count {run['observation_period_count']}"

    assert _dec(effect["rows"][a_search]["contribution_units"]) == _dec(
        fixtures.F1_EFFECT_CONTRIBUTION_A_SEARCH
    ), (
        "EFFECT_PERIOD A_SEARCH contribution_units should be "
        f"{fixtures.F1_EFFECT_CONTRIBUTION_A_SEARCH}, got "
        f"{effect['rows'][a_search]['contribution_units']}"
    )
    assert _dec(effect["rows"][b_social]["contribution_units"]) == _dec(
        fixtures.F1_EFFECT_CONTRIBUTION_B_SOCIAL
    ), (
        "EFFECT_PERIOD B_SOCIAL contribution_units should be "
        f"{fixtures.F1_EFFECT_CONTRIBUTION_B_SOCIAL}, got "
        f"{effect['rows'][b_social]['contribution_units']}"
    )
    assert _dec(effect["run"]["baseline_sales_units"]) == _dec(
        fixtures.F1_EFFECT_BASELINE_UNITS
    ), (
        "EFFECT_PERIOD baseline_sales_units should be "
        f"{fixtures.F1_EFFECT_BASELINE_UNITS}, got "
        f"{effect['run']['baseline_sales_units']}"
    )

    assert _dec(spend["rows"][a_search]["contribution_units"]) == _dec(
        fixtures.F1_SPEND_CONTRIBUTION_A_SEARCH
    ), (
        "SPEND_PERIOD A_SEARCH contribution_units should be "
        f"{fixtures.F1_SPEND_CONTRIBUTION_A_SEARCH}, got "
        f"{spend['rows'][a_search]['contribution_units']}"
    )
    assert _dec(spend["rows"][b_social]["contribution_units"]) == _dec(
        fixtures.F1_SPEND_CONTRIBUTION_B_SOCIAL
    ), (
        "SPEND_PERIOD B_SOCIAL contribution_units should be "
        f"{fixtures.F1_SPEND_CONTRIBUTION_B_SOCIAL}, got "
        f"{spend['rows'][b_social]['contribution_units']}"
    )
    assert _dec(spend["run"]["baseline_sales_units"]) == _dec(
        fixtures.F1_SPEND_BASELINE_UNITS
    ), (
        "SPEND_PERIOD baseline_sales_units should be "
        f"{fixtures.F1_SPEND_BASELINE_UNITS}, got "
        f"{spend['run']['baseline_sales_units']}"
    )

    # The saturating response curve is concave, so the larger but flatter
    # SPEND_PERIOD series does not buy more units on every channel: A_SEARCH
    # rises while B_SOCIAL falls off the very same switch.
    assert _dec(spend["rows"][a_search]["contribution_units"]) > _dec(
        effect["rows"][a_search]["contribution_units"]
    ), "A_SEARCH should gain units under SPEND_PERIOD"
    assert _dec(spend["rows"][b_social]["contribution_units"]) < _dec(
        effect["rows"][b_social]["contribution_units"]
    ), "B_SOCIAL should lose units under SPEND_PERIOD"

    assertions.assert_baseline_identity(effect["run"], effect["listed"])
    assertions.assert_baseline_identity(spend["run"], spend["listed"])


def test_adstocked_spend_series_and_mode_stamp_follow_the_carryover_mode(api):
    """PRD 3.4: "The adstocked value for a period is that period's own raw spend plus, for each lag from one up to the smaller of the channel's maximum lag and the number of periods that precede this one, the raw spend of the period that many positions earlier multiplied by the decay rate raised to the power of that lag; the whole sum is then rounded half-up to a whole cent."
    PRD 3.4: "A single geometric gain is formed once for the channel as the sum, over every lag from zero through the channel's maximum lag inclusive, of the decay rate raised to that lag. Each period's adstocked value is then that period's own raw spend multiplied by this gain, rounded half-up to a whole cent."
    PRD 3.4: "Whichever variant applies, the resulting integer-cent series is stored on the channel's decomposition row as `adstocked_spend_series`, in ascending period order, and `mean_adstocked_spend_cents` is stored as the sum of that series divided by the window's period count, rounded half-up to a whole cent."
    PRD 3.4: "The variant actually used is recorded on the row as `attribution_mode_used`, copied from the run's `carryover_attribution_mode` as it stood when the row was produced, so a row remains interpretable even after the run's specification is superseded by a later one."

    Design: Difficulty/dual_variant_calc/carryover_mode_variant_divergence_on_channel_contribution
    """
    ctx = _both_carryover_variants(api)
    a_search = ctx["a_search"]["id"]
    b_social = ctx["b_social"]["id"]
    effect = ctx["variants"]["EFFECT_PERIOD"]
    spend = ctx["variants"]["SPEND_PERIOD"]

    expected = {
        "EFFECT_PERIOD": {
            a_search: (
                fixtures.F1_EFFECT_SERIES_A_SEARCH,
                fixtures.F1_EFFECT_MEAN_A_SEARCH,
            ),
            b_social: (
                fixtures.F1_EFFECT_SERIES_B_SOCIAL,
                fixtures.F1_EFFECT_MEAN_B_SOCIAL,
            ),
        },
        "SPEND_PERIOD": {
            a_search: (
                fixtures.F1_SPEND_SERIES_A_SEARCH,
                fixtures.F1_SPEND_MEAN_A_SEARCH,
            ),
            b_social: (
                fixtures.F1_SPEND_SERIES_B_SOCIAL,
                fixtures.F1_SPEND_MEAN_B_SOCIAL,
            ),
        },
    }

    for mode, per_channel in expected.items():
        for channel_id, (series, mean) in per_channel.items():
            row = ctx["variants"][mode]["rows"][channel_id]
            assert assertions.series_of(row) == series, (
                f"{mode} adstocked_spend_series should be {series}, got "
                f"{row['adstocked_spend_series']}"
            )
            assert row["mean_adstocked_spend_cents"] == mean, (
                f"{mode} mean_adstocked_spend_cents should be {mean}, got "
                f"{row['mean_adstocked_spend_cents']}"
            )
            assert row["attribution_mode_used"] == mode, (
                f"attribution_mode_used should copy {mode}, got "
                f"{row['attribution_mode_used']}"
            )
            assert row["is_current"] is True, "a fresh fit writes current rows"

    # No spend before the window is imputed, so the earliest EFFECT_PERIOD
    # periods draw on fewer lags and the whole series totals less than the
    # untruncated geometric total the SPEND_PERIOD gain credits back.
    assert sum(assertions.series_of(spend["rows"][a_search])) > sum(
        assertions.series_of(effect["rows"][a_search])
    ), "the SPEND_PERIOD series total should exceed the EFFECT_PERIOD one"
    assert sum(assertions.series_of(spend["rows"][b_social])) > sum(
        assertions.series_of(effect["rows"][b_social])
    ), "the SPEND_PERIOD series total should exceed the EFFECT_PERIOD one"


def test_raw_attributed_spend_is_invariant_while_returns_diverge(api):
    """PRD 3.4: "`attributed_spend_cents` is the sum of `spend_cents` over that channel's non-superseded spend observations inside the training window — raw spend, never the adstocked figure."
    PRD 3.4: "`contribution_revenue_cents` is `contribution_units` multiplied by the run's `unit_price_cents`, rounded half-up to a whole cent."
    PRD 3.4: "`average_roi` is `contribution_revenue_cents` divided by `attributed_spend_cents`, rounded half-up to four decimal places, and is reported as exactly 0.0000 when `attributed_spend_cents` is zero rather than being left undefined."
    PRD 3.4: "Because the raw spend denominator behind `average_roi` is identical under both attribution modes while the numerator moves, the two variants' returns remain directly comparable and their divergence is attributable entirely to the decomposition."

    Design: Difficulty/dual_variant_calc/carryover_mode_variant_divergence_on_channel_contribution
    """
    ctx = _both_carryover_variants(api)
    a_search = ctx["a_search"]["id"]
    b_social = ctx["b_social"]["id"]
    effect = ctx["variants"]["EFFECT_PERIOD"]
    spend = ctx["variants"]["SPEND_PERIOD"]

    for mode, variant in ctx["variants"].items():
        assert (
            variant["rows"][a_search]["attributed_spend_cents"]
            == fixtures.F1_ATTRIBUTED_SPEND_A_SEARCH
        ), (
            f"{mode} A_SEARCH attributed_spend_cents should stay at the raw "
            f"{fixtures.F1_ATTRIBUTED_SPEND_A_SEARCH}, got "
            f"{variant['rows'][a_search]['attributed_spend_cents']}"
        )
        assert (
            variant["rows"][b_social]["attributed_spend_cents"]
            == fixtures.F1_ATTRIBUTED_SPEND_B_SOCIAL
        ), (
            f"{mode} B_SOCIAL attributed_spend_cents should stay at the raw "
            f"{fixtures.F1_ATTRIBUTED_SPEND_B_SOCIAL}, got "
            f"{variant['rows'][b_social]['attributed_spend_cents']}"
        )

    revenue_expectations = [
        (effect, a_search, fixtures.F1_EFFECT_REVENUE_A_SEARCH),
        (effect, b_social, fixtures.F1_EFFECT_REVENUE_B_SOCIAL),
        (spend, a_search, fixtures.F1_SPEND_REVENUE_A_SEARCH),
        (spend, b_social, fixtures.F1_SPEND_REVENUE_B_SOCIAL),
    ]
    for variant, channel_id, expected_cents in revenue_expectations:
        row = variant["rows"][channel_id]
        assert row["contribution_revenue_cents"] == expected_cents, (
            f"{row['attribution_mode_used']} contribution_revenue_cents should be "
            f"{expected_cents}, got {row['contribution_revenue_cents']}"
        )

    roi_expectations = [
        (effect, a_search, fixtures.F1_EFFECT_AVERAGE_ROI_A_SEARCH),
        (effect, b_social, fixtures.F1_EFFECT_AVERAGE_ROI_B_SOCIAL),
        (spend, a_search, fixtures.F1_SPEND_AVERAGE_ROI_A_SEARCH),
        (spend, b_social, fixtures.F1_SPEND_AVERAGE_ROI_B_SOCIAL),
    ]
    for variant, channel_id, expected_roi in roi_expectations:
        row = variant["rows"][channel_id]
        assert _dec(row["average_roi"]) == _dec(expected_roi), (
            f"{row['attribution_mode_used']} average_roi should be {expected_roi}, "
            f"got {row['average_roi']}"
        )

    assert _dec(effect["rows"][a_search]["average_roi"]) != _dec(
        spend["rows"][a_search]["average_roi"]
    ), "the two decompositions must not agree on A_SEARCH average_roi"
    assert _dec(effect["rows"][b_social]["average_roi"]) != _dec(
        spend["rows"][b_social]["average_roi"]
    ), "the two decompositions must not agree on B_SOCIAL average_roi"


def test_marginal_roi_and_interval_track_the_mean_adstocked_series(api):
    """PRD 3.4: "It is the run's `unit_price_cents` multiplied by the channel's `response_ceiling_units`, multiplied by the channel's `saturation_half_point_cents`, divided by the square of the quantity formed by adding `mean_adstocked_spend_cents` to `saturation_half_point_cents`, rounded half-up to six decimal places."
    PRD 3.4: "`ci_half_width_pct` is 40.0 divided by the square root of the run's `observation_period_count`, rounded half-up to two decimal places; it is therefore identical for every channel of a run."
    PRD 3.4: "`ci_low_units` is `contribution_units` multiplied by one minus one-hundredth of `ci_half_width_pct`, rounded half-up to four decimals, and `ci_high_units` is `contribution_units` multiplied by one plus one-hundredth of `ci_half_width_pct`, rounded half-up to four decimals."

    Design: Difficulty/dual_variant_calc/carryover_mode_variant_divergence_on_channel_contribution
    """
    ctx = _both_carryover_variants(api)
    a_search = ctx["a_search"]["id"]
    b_social = ctx["b_social"]["id"]
    effect = ctx["variants"]["EFFECT_PERIOD"]
    spend = ctx["variants"]["SPEND_PERIOD"]

    marginal_expectations = [
        (effect, a_search, fixtures.F1_EFFECT_MARGINAL_ROI_A_SEARCH),
        (effect, b_social, fixtures.F1_EFFECT_MARGINAL_ROI_B_SOCIAL),
        (spend, a_search, fixtures.F1_SPEND_MARGINAL_ROI_A_SEARCH),
        (spend, b_social, fixtures.F1_SPEND_MARGINAL_ROI_B_SOCIAL),
    ]
    for variant, channel_id, expected in marginal_expectations:
        row = variant["rows"][channel_id]
        assert _dec(row["marginal_roi"]) == _dec(expected), (
            f"{row['attribution_mode_used']} marginal_roi should be {expected}, "
            f"got {row['marginal_roi']}"
        )

    # The half width depends only on how many periods the run observed, so the
    # switch cannot move it on either channel of either run.
    for mode, variant in ctx["variants"].items():
        for channel_id in (a_search, b_social):
            row = variant["rows"][channel_id]
            assert _dec(row["ci_half_width_pct"]) == _dec(
                fixtures.F1_CI_HALF_WIDTH_PCT
            ), (
                f"{mode} ci_half_width_pct should be "
                f"{fixtures.F1_CI_HALF_WIDTH_PCT}, got {row['ci_half_width_pct']}"
            )

    assert _dec(effect["rows"][a_search]["ci_low_units"]) == _dec(
        fixtures.F1_EFFECT_CI_LOW_A_SEARCH
    ), "EFFECT_PERIOD A_SEARCH ci_low_units"
    assert _dec(effect["rows"][a_search]["ci_high_units"]) == _dec(
        fixtures.F1_EFFECT_CI_HIGH_A_SEARCH
    ), "EFFECT_PERIOD A_SEARCH ci_high_units"
    assert _dec(spend["rows"][a_search]["ci_low_units"]) == _dec(
        fixtures.F1_SPEND_CI_LOW_A_SEARCH
    ), "SPEND_PERIOD A_SEARCH ci_low_units"
    assert _dec(spend["rows"][a_search]["ci_high_units"]) == _dec(
        fixtures.F1_SPEND_CI_HIGH_A_SEARCH
    ), "SPEND_PERIOD A_SEARCH ci_high_units"


def test_readout_method_diverges_on_measured_lift_from_identical_counts(api):
    """PRD 3.6: "Under `DIFF_IN_DIFF`, the difference-in-differences quantity is the change in the treatment rate from pre-period to post-period, minus the change in the control rate over the same two periods. `measured_lift_pct` is one hundred multiplied by that quantity, divided by the **observed** post-period control rate, rounded half-up to two decimal places."
    PRD 3.6: "The control arm's post-period rate is then rescaled by that weight, and `measured_lift_pct` is one hundred multiplied by the difference between the treatment post-period rate and the rescaled control rate, divided by the **rescaled** control rate, rounded half-up to two decimal places."

    Design: Difficulty/dual_variant_calc/readout_method_variant_divergence_on_experiment_lift
    """
    ctx = _both_readout_variants(api)
    did = ctx["experiments"]["DIFF_IN_DIFF"]
    synthetic = ctx["experiments"]["SYNTHETIC_CONTROL"]

    assert did["status"] == "READ_OUT", f"got {did['status']}"
    assert synthetic["status"] == "READ_OUT", f"got {synthetic['status']}"

    assert _dec(did["measured_lift_pct"]) == _dec(
        fixtures.F1_DID_MEASURED_LIFT_PCT
    ), (
        "the difference-in-differences estimator should report "
        f"{fixtures.F1_DID_MEASURED_LIFT_PCT}, got {did['measured_lift_pct']}"
    )
    assert _dec(synthetic["measured_lift_pct"]) == _dec(
        fixtures.F1_SYNTHETIC_MEASURED_LIFT_PCT
    ), (
        "the synthetic-control estimator should report "
        f"{fixtures.F1_SYNTHETIC_MEASURED_LIFT_PCT}, got "
        f"{synthetic['measured_lift_pct']}"
    )

    # Same counts, same arms, different estimator: the whole gap belongs to the
    # choice between differencing the drift away and rescaling the control rate.
    gap = _dec(synthetic["measured_lift_pct"]) - _dec(did["measured_lift_pct"])
    assert gap == _dec(fixtures.F1_SYNTHETIC_MEASURED_LIFT_PCT) - _dec(
        fixtures.F1_DID_MEASURED_LIFT_PCT
    ), f"the two estimators should differ by exactly that margin, got {gap}"
    assert gap != Decimal("0"), "the two estimators must not agree here"


def test_synthetic_control_weight_is_derived_only_by_its_own_estimator(api):
    """PRD 3.6: "This estimator removes the control arm's own pre-to-post drift, and `synthetic_control_weight` is not derived at all under it — the field stays null."
    PRD 3.6: "`synthetic_control_weight` is the pre-period treatment rate divided by the pre-period control rate, rounded half-up to six decimal places."

    Design: Difficulty/dual_variant_calc/readout_method_variant_divergence_on_experiment_lift
    """
    ctx = _both_readout_variants(api)
    did = ctx["experiments"]["DIFF_IN_DIFF"]
    synthetic = ctx["experiments"]["SYNTHETIC_CONTROL"]

    assert did["readout_method"] == "DIFF_IN_DIFF", did["readout_method"]
    assert did["synthetic_control_weight"] is None, (
        "the difference-in-differences readout must leave synthetic_control_weight "
        f"null, got {did['synthetic_control_weight']!r}"
    )

    assert synthetic["readout_method"] == "SYNTHETIC_CONTROL", (
        synthetic["readout_method"]
    )
    assert _dec(synthetic["synthetic_control_weight"]) == _dec(
        fixtures.F1_SYNTHETIC_WEIGHT
    ), (
        "synthetic_control_weight should be "
        f"{fixtures.F1_SYNTHETIC_WEIGHT}, got "
        f"{synthetic['synthetic_control_weight']}"
    )
    assertions.assert_decimal_places(
        synthetic["synthetic_control_weight"], 6, "synthetic_control_weight"
    )


def test_lift_interval_half_width_is_shared_by_both_readout_methods(api):
    """PRD 3.6: "The interval half-width is identical under both estimators, because the observed post-period control rate is its denominator in both cases."
    PRD 3.6: "`lift_ci_half_width_pct` is one hundred multiplied by 1.96, multiplied by that standard error, divided by the observed post-period control rate, rounded half-up to two decimal places."
    PRD 3.6: "`lift_ci_low_pct` is `measured_lift_pct` minus `lift_ci_half_width_pct`, rounded half-up to two decimals, and `lift_ci_high_pct` is `measured_lift_pct` plus `lift_ci_half_width_pct`, rounded half-up to two decimals."

    Design: Difficulty/dual_variant_calc/readout_method_variant_divergence_on_experiment_lift
    """
    ctx = _both_readout_variants(api)
    did = ctx["experiments"]["DIFF_IN_DIFF"]
    synthetic = ctx["experiments"]["SYNTHETIC_CONTROL"]

    for method, row in ctx["experiments"].items():
        assert _dec(row["lift_ci_half_width_pct"]) == _dec(
            fixtures.F1_LIFT_CI_HALF_WIDTH_PCT
        ), (
            f"{method} lift_ci_half_width_pct should be "
            f"{fixtures.F1_LIFT_CI_HALF_WIDTH_PCT}, got "
            f"{row['lift_ci_half_width_pct']}"
        )

    assert _dec(did["lift_ci_half_width_pct"]) - _dec(
        synthetic["lift_ci_half_width_pct"]
    ) == Decimal("0"), "the two half widths must not differ by anything at all"

    assert _dec(did["lift_ci_low_pct"]) == _dec(fixtures.F1_DID_CI_LOW_PCT), (
        f"got {did['lift_ci_low_pct']}"
    )
    assert _dec(did["lift_ci_high_pct"]) == _dec(fixtures.F1_DID_CI_HIGH_PCT), (
        f"got {did['lift_ci_high_pct']}"
    )
    assert _dec(synthetic["lift_ci_low_pct"]) == _dec(
        fixtures.F1_SYNTHETIC_CI_LOW_PCT
    ), f"got {synthetic['lift_ci_low_pct']}"
    assert _dec(synthetic["lift_ci_high_pct"]) == _dec(
        fixtures.F1_SYNTHETIC_CI_HIGH_PCT
    ), f"got {synthetic['lift_ci_high_pct']}"


def test_both_readout_methods_store_the_same_counts_and_realised_arms(api):
    """PRD 3.6: "The four counts are stored, the four lift fields are set, `status` becomes `READ_OUT` and `version` increments."
    PRD 3.6: "An `AUDIENCE_SPLIT` experiment reaches `RUNNING` straight from `DESIGN_LOCKED`, and that step (re)asserts `treatment_population` from `planned_treatment_population` and `control_population` from `planned_control_population`."
    PRD 3.6: "Four rates are formed from the counts and the realised arm populations: the post-period treatment rate is `treatment_conversions` divided by `treatment_population`; the post-period control rate is `control_conversions` divided by `control_population`; the pre-period treatment rate is `pre_treatment_conversions` divided by `treatment_population`; and the pre-period control rate is `pre_control_conversions` divided by `control_population`."

    Design: Difficulty/dual_variant_calc/readout_method_variant_divergence_on_experiment_lift
    """
    ctx = _both_readout_variants(api)

    expected_counts = {
        "treatment_conversions": factories.READOUT_TREATMENT_CONVERSIONS,
        "control_conversions": factories.READOUT_CONTROL_CONVERSIONS,
        "pre_treatment_conversions": factories.READOUT_PRE_TREATMENT_CONVERSIONS,
        "pre_control_conversions": factories.READOUT_PRE_CONTROL_CONVERSIONS,
    }
    for method, row in ctx["experiments"].items():
        for field, expected in expected_counts.items():
            assert row[field] == expected, (
                f"{method} {field} should be stored as {expected}, got {row[field]}"
            )
        assert row["treatment_population"] == factories.EXPERIMENT_ARM_POPULATION, (
            f"{method} treatment_population should be asserted from the plan, got "
            f"{row['treatment_population']}"
        )
        assert row["control_population"] == factories.EXPERIMENT_ARM_POPULATION, (
            f"{method} control_population should be asserted from the plan, got "
            f"{row['control_population']}"
        )
        for field in (
            "measured_lift_pct",
            "lift_ci_half_width_pct",
            "lift_ci_low_pct",
            "lift_ci_high_pct",
        ):
            assert row[field] is not None, f"{method} left {field} null"
