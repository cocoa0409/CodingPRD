"""Derived quantities: the numbers the contract computes rather than accepts.

Every claim in this module is arithmetic the service performs on its own — the
market's computed data posture, the adstock decay series and the input set it
draws on, the run-level sales aggregates, the holdout backtest, the confidence
interval, the two return-on-investment rates, the two-pass budget waterfall's
constraint markers, the refresh stability score, and the declared decimal place
of each published figure. The canonical two-channel market with its four-period
weekly window is the fixture behind all of them, because the contract's
arithmetic is only observable once a run has been fitted against sealed data.

Each expected figure below is pinned as a literal: the contract fixes both the
formula and the rounding point of every one of them, so a figure is stated once
and never re-derived from the response it is checking.
"""

from decimal import Decimal

from test_helpers import (
    assertions,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_success,
)

# --- Figures the canonical chain produces that are not already pinned in the
# --- shared fixture module.

# The interval bounds of B_SOCIAL, whose contribution_units is 2014.2857.
_B_SOCIAL_CI_LOW_UNITS = 1611.4286
_B_SOCIAL_CI_HIGH_UNITS = 2417.1428

# What B_SOCIAL's contribution_units would have been had the four per-period
# saturation terms each been rounded before being summed. The contract mandates
# a single rounding over the exact sum, so this figure must never appear.
_FORBIDDEN_PRE_ROUNDED_B_SOCIAL_UNITS = 2014.2858

# A first, overstated A_SEARCH filing for the window's opening period, which a
# restatement then supersedes.
_OVERSTATED_SPEND_CENTS = 9999999
_LIVE_SPEND_OBSERVATION_COUNT = 8

# Channel spend bounds that make the waterfall bind, first on a ceiling and then
# on a floor, over the same 4000000-cent plan.
_A_SEARCH_CAPPED_MAX_CENTS = 2000000
_A_SEARCH_RESTORED_MAX_CENTS = 3000000
_B_SOCIAL_RAISED_MIN_CENTS = 1800000

# The ceiling-bound plan: pass one lands 2000000 / 2000000 for a churn of
# 1000000, which pins the fee, and pass two spends the reduced balance.
_CEILING_FEE_CENTS = 5000
_CEILING_A_SEARCH_ALLOCATED_CENTS = 2000000
_CEILING_B_SOCIAL_ALLOCATED_CENTS = 1900000
_CEILING_ALLOCATED_TOTAL_CENTS = 3900000
_CEILING_UNALLOCATED_CENTS = 95000
_CEILING_SHIFTED_A_SEARCH_CENTS = 500000
_CEILING_SHIFTED_B_SOCIAL_CENTS = 600000
_CEILING_SHIFTED_TOTAL_CENTS = 1100000

# The floor-bound plan: pass one lands 2200000 / 1800000 for a churn of 1400000.
_FLOOR_FEE_CENTS = 7000
_FLOOR_A_SEARCH_ALLOCATED_CENTS = 2100000
_FLOOR_B_SOCIAL_ALLOCATED_CENTS = 1800000
_FLOOR_ALLOCATED_TOTAL_CENTS = 3900000
_FLOOR_UNALLOCATED_CENTS = 93000
_FLOOR_SHIFTED_A_SEARCH_CENTS = 600000
_FLOOR_SHIFTED_B_SOCIAL_CENTS = 700000
_FLOOR_SHIFTED_TOTAL_CENTS = 1300000

# A refresh that drops B_SOCIAL from the specification: inside the channel union
# B_SOCIAL's average_roi falls to 0, so the drift total is 11.2487 against a base
# total of 21.4496 and the score lands below the 0.6000 floor.
_A_SEARCH_ONLY_STABILITY_SCORE = 0.4756
_A_SEARCH_ONLY_HOLDOUT_MAPE_PCT = 10.82
_FIRST_REFRESH_GENERATION = 1
_SECOND_REFRESH_GENERATION = 2


def _dec(value) -> Decimal:
    """A JSON number as an exact decimal, so a pinned figure compares exactly."""
    return Decimal(str(value))


def _by_channel(rows):
    """The contribution or allocation rows of a run, indexed by channel."""
    return assertions.rows_by(rows, "channel_id")


def _sealed_window_with_restated_opening_period(api):
    """The canonical window whose opening A_SEARCH period was restated once.

    A_SEARCH's 2026-08-03 spend is filed first at an overstated 9999999 cents
    and then re-filed at the canonical 400000, which supersedes the incumbent.
    The remaining seven canonical rows follow, so the window carries nine spend
    rows of which eight are live, and the live set is exactly the canonical one.
    """
    ctx = fixtures.market_with_channels(api)
    window = fixtures.create_data_window(api, ctx["market"]["id"])
    ctx["window"] = window
    ctx["sales"] = fixtures.file_sales_rows(api, window["id"])
    entries = [
        (
            ctx["a_search"]["id"],
            factories.WINDOW_PERIODS[0],
            {"spend_cents": _OVERSTATED_SPEND_CENTS, "impressions": 4000},
        )
    ]
    entries.extend(
        fixtures.f1_spend_entries(ctx["a_search"]["id"], ctx["b_social"]["id"])
    )
    ctx["spend"] = fixtures.file_spend_chain(api, window["id"], entries)
    return fixtures.sealed_window(api, ctx)


def test_market_posture_first_match_wins_frozen_over_restricted(api):
    """PRD §2.8: "The three tests are evaluated in a fixed order and the first one that matches determines the posture."
    PRD §2.8: "First: if any data window belonging to the market is in `REOPENED` status, the posture is `FROZEN`."
    PRD §2.8: "Second: if the market has no model run whose `publication_status` is `PUBLISHED`, or that published run's `calibration_status` is `STALE`, or the market has no data window in `SEALED` status, the posture is `RESTRICTED`."
    PRD §2.8: "A market also publishes two convenience projections alongside its posture: `published_model_run_id`, which resolves to the `id` of the single run of that market whose `publication_status` is `PUBLISHED` and is null when no such run exists, and the population aggregates described in §3.1."
    PRD §3.3: "The transition sets `status` to `REOPENED`, increases `reopen_count` by one, and bumps `version`."
    PRD §3.3: "The first hop reaches the runs: every model run whose training window is this one and whose `fit_status` is `FITTED` moves to `fit_status` `STALE_FIT` and simultaneously has its `validation_status` reset to `UNVALIDATED`, because a backtest against retracted data proves nothing."

    Design: Corner/calculations/market_data_posture_first_match_wins_frozen_beats_restricted
    """
    ctx = fixtures.published_run(api)
    run_id = ctx["run"]["id"]
    window_id = ctx["window"]["id"]

    before = fixtures.refresh_market(api, ctx)
    assertions.assert_market(before)
    assert before["data_posture"] == "OPEN", (
        "a market with a sealed window and a published, non-stale run is OPEN, "
        f"got {before['data_posture']}"
    )
    assert before["published_model_run_id"] == run_id, before["published_model_run_id"]

    validate_success(
        api.reopen_data_window(
            window_id,
            factories.reopen_payload("Agency restated week 3 spend."),
            test_users.DATA_ENGINEER,
        )
    )

    reopened = fixtures.refresh_market(api, ctx)
    assert reopened["data_posture"] == "FROZEN", (
        "the reopen leaves the market with a REOPENED window and no SEALED one, "
        "so both the first and the second test match and the first must win; got "
        f"{reopened['data_posture']}"
    )
    assert reopened["published_model_run_id"] == run_id, (
        "the reopen staled the fit, not the publication, so the market still "
        f"projects its published run; got {reopened['published_model_run_id']}"
    )

    validate_success(api.seal_data_window(window_id, test_users.DATA_ENGINEER))

    after = fixtures.refresh_market(api, ctx)
    assert after["data_posture"] == "OPEN", (
        "re-sealing removes the REOPENED row and restores a SEALED one, so both "
        f"posture tests go false in a single recomputation; got {after['data_posture']}"
    )

    run = fixtures.refresh_run(api, ctx)
    assertions.assert_run_state(run, "STALE_FIT", "UNVALIDATED", "NOT_REQUIRED", "PUBLISHED")

    window = fixtures.refresh_window(api, ctx)
    assert window["status"] == "SEALED", window["status"]
    assert window["reopen_count"] == 1, window["reopen_count"]


def test_adstock_series_truncates_its_carryover_at_the_window_head(api):
    """PRD §3.4: "The adstocked value for a period is that period's own raw spend plus, for each lag from one up to the smaller of the channel's maximum lag and the number of periods that precede this one, the raw spend of the period that many positions earlier multiplied by the decay rate raised to the power of that lag; the whole sum is then rounded half-up to a whole cent."
    PRD §3.4: "Because no spend from before the window is imputed, the earliest periods of the series are truncated — they simply have fewer lags available to draw on — and the series total therefore comes out smaller than the un-truncated geometric total would be."
    PRD §3.4: "Whichever variant applies, the resulting integer-cent series is stored on the channel's decomposition row as `adstocked_spend_series`, in ascending period order, and `mean_adstocked_spend_cents` is stored as the sum of that series divided by the window's period count, rounded half-up to a whole cent."

    Design: Corner/calculations/adstock_transform_lag_truncation_series
    """
    ctx = fixtures.fitted_run(api, carryover_attribution_mode="EFFECT_PERIOD")
    rows = fixtures.contributions_of(api, ctx["run"]["id"])
    assert len(rows) == 2, f"a two-channel fit writes two rows, got {len(rows)}"
    by_channel = _by_channel(rows)

    a_search = by_channel[ctx["a_search"]["id"]]
    b_social = by_channel[ctx["b_social"]["id"]]
    assertions.assert_channel_contribution(a_search)
    assertions.assert_channel_contribution(b_social)
    assert a_search["attribution_mode_used"] == "EFFECT_PERIOD", a_search
    assert b_social["attribution_mode_used"] == "EFFECT_PERIOD", b_social

    assert assertions.series_of(a_search) == fixtures.F1_EFFECT_SERIES_A_SEARCH, (
        "A_SEARCH carries decay 0.50 over two lag periods on raw spend "
        f"[400000, 600000, 300000, 500000]; got {a_search['adstocked_spend_series']}"
    )
    assert a_search["mean_adstocked_spend_cents"] == fixtures.F1_EFFECT_MEAN_A_SEARCH, (
        a_search["mean_adstocked_spend_cents"]
    )

    assert assertions.series_of(b_social) == fixtures.F1_EFFECT_SERIES_B_SOCIAL, (
        "B_SOCIAL admits only lag one, so its final period never picks up a "
        f"second-lag term; got {b_social['adstocked_spend_series']}"
    )
    assert b_social["mean_adstocked_spend_cents"] == fixtures.F1_EFFECT_MEAN_B_SOCIAL, (
        b_social["mean_adstocked_spend_cents"]
    )

    assert (
        a_search["adstocked_spend_series"][0]
        == factories.F1_SPEND_A_SEARCH[0]["spend_cents"]
    ), (
        "the opening period has no periods preceding it, so its adstocked value "
        "is its raw spend exactly and no pre-window spend is imputed"
    )
    assert (
        b_social["adstocked_spend_series"][0]
        == factories.F1_SPEND_B_SOCIAL[0]["spend_cents"]
    ), b_social["adstocked_spend_series"]


def test_fit_reads_only_the_live_spend_row_of_a_restated_period(api):
    """PRD §3.4: "The raw spend for a period is the sum of `spend_cents` across that channel's spend observations whose `period_start_date` equals that period's start and whose `superseded_by_id` is null; superseded restatements are excluded entirely, and a period in which the channel filed nothing contributes raw spend of zero rather than being skipped."
    PRD §3.4: "`attributed_spend_cents` is the sum of `spend_cents` over that channel's non-superseded spend observations inside the training window — raw spend, never the adstocked figure."
    PRD §3.2: "The incumbent's `superseded_by_id` is set to the new row's identifier, and the new row's `is_restatement` becomes true."
    PRD §3.2: "Every accepted spend write recomputes the parent window's `spend_observation_count` over its non-superseded rows only, increments the window's `version`, and stamps the observation's `data_window_version_after` with the post-write value."

    Design: Corner/calculations/adstock_input_set_excludes_superseded_spend_rows
    """
    ctx = _sealed_window_with_restated_opening_period(api)
    overstated = ctx["spend"][0]
    restatement = ctx["spend"][1]
    run = fixtures.create_run(api, ctx, carryover_attribution_mode="EFFECT_PERIOD")

    fitted = validate_success(api.fit_model_run(run["id"], test_users.MODELER))
    assert fitted["fit_status"] == "FITTED", fitted["fit_status"]
    assert fitted["modeled_sales_units"] == fixtures.F1_MODELED_SALES_UNITS, fitted
    assert fitted["unit_price_cents"] == fixtures.F1_UNIT_PRICE_CENTS, fitted
    assert _dec(fitted["baseline_sales_units"]) == _dec(
        fixtures.F1_EFFECT_BASELINE_UNITS
    ), fitted["baseline_sales_units"]

    rows = fixtures.contributions_of(api, run["id"])
    a_search = _by_channel(rows)[ctx["a_search"]["id"]]
    assert assertions.series_of(a_search) == fixtures.F1_EFFECT_SERIES_A_SEARCH, (
        "the superseded 9999999-cent row is absent from every period of the "
        f"adstocked series; got {a_search['adstocked_spend_series']}"
    )
    assert a_search["attributed_spend_cents"] == fixtures.F1_ATTRIBUTED_SPEND_A_SEARCH, (
        "raw attributed spend counts the live rows only; got "
        f"{a_search['attributed_spend_cents']}"
    )
    assert _dec(a_search["contribution_units"]) == _dec(
        fixtures.F1_EFFECT_CONTRIBUTION_A_SEARCH
    ), a_search["contribution_units"]
    assert _dec(a_search["average_roi"]) == _dec(
        fixtures.F1_EFFECT_AVERAGE_ROI_A_SEARCH
    ), a_search["average_roi"]

    superseded = validate_success(
        api.get_spend_observation(overstated["id"], test_users.DATA_ENGINEER)
    )
    assert superseded["spend_cents"] == _OVERSTATED_SPEND_CENTS, superseded
    assert superseded["superseded_by_id"] == restatement["id"], superseded

    live = validate_success(
        api.get_spend_observation(restatement["id"], test_users.DATA_ENGINEER)
    )
    assert live["is_restatement"] is True, live
    assert live["superseded_by_id"] is None, live

    window = fixtures.refresh_window(api, ctx)
    assert window["spend_observation_count"] == _LIVE_SPEND_OBSERVATION_COUNT, (
        "nine rows were written but only eight are live; got "
        f"{window['spend_observation_count']}"
    )


def test_unit_price_is_one_ratio_of_the_window_totals(api):
    """PRD §3.4: "Before touching any channel, the fit computes three run-level aggregates over **all** sales observations of the training window, holdout periods included."
    PRD §3.4: "`observation_period_count` is the number of sales observations found."
    PRD §3.4: "`modeled_sales_units` is the sum of their `units_sold`."
    PRD §3.4: "`unit_price_cents` is the sum of their `revenue_cents` divided by the sum of their `units_sold`, rounded half-up to a whole cent."
    PRD §3.4: "The holdout split affects only the backtest described in §3.5; it never narrows the population used for the price or the sales total."
    PRD §3.4: "`baseline_sales_units` is `modeled_sales_units` minus the sum of every included channel's `contribution_units`, rounded half-up to four decimal places, so that the channel contributions plus the baseline reconstruct the modelled sales total exactly."

    Design: Corner/calculations/model_run_aggregates_unit_price_from_window_totals
    """
    ctx = fixtures.fitted_run(api, carryover_attribution_mode="EFFECT_PERIOD")
    run = validate_success(api.get_model_run(ctx["run"]["id"], test_users.AUDITOR))
    assertions.assert_model_run(run)

    assert run["observation_period_count"] == fixtures.F1_OBSERVATION_PERIOD_COUNT, (
        "all four sales periods are counted, the held-out one included; got "
        f"{run['observation_period_count']}"
    )
    assert run["holdout_periods"] == 1, run["holdout_periods"]
    assert run["modeled_sales_units"] == fixtures.F1_MODELED_SALES_UNITS, (
        "the window's four sales rows total 23000 units; got "
        f"{run['modeled_sales_units']}"
    )
    assertions.assert_cents(run["unit_price_cents"], "unit_price_cents")
    assert run["unit_price_cents"] == fixtures.F1_UNIT_PRICE_CENTS, (
        "the price is the single ratio of the window's 115600000 cents to its "
        "23000 units, rounded half-up to a whole cent, not the mean of the four "
        f"per-period average prices; got {run['unit_price_cents']}"
    )

    assert _dec(run["baseline_sales_units"]) == _dec(
        fixtures.F1_EFFECT_BASELINE_UNITS
    ), run["baseline_sales_units"]
    contributions = fixtures.contributions_of(api, run["id"])
    assertions.assert_baseline_identity(run, contributions)


def test_holdout_backtest_scores_the_single_held_out_period(api):
    """PRD §3.5: "First, a flat per-period baseline is formed as `baseline_sales_units` divided by `observation_period_count`, rounded half-up to four decimal places."
    PRD §3.5: "Then, for each holdout period, a prediction is formed as that per-period baseline plus the sum, across every included channel, of that channel's saturated per-period unit contribution for that period **each rounded half-up to four decimal places before being added**, with the resulting total rounded half-up to four decimal places."
    PRD §3.5: "`holdout_mape_pct` is then one hundred multiplied by the sum, over the holdout periods, of the absolute difference between prediction and actual divided by that period's actual, all divided by the number of holdout periods, rounded half-up to two decimal places."
    PRD §3.5: "`validation_status` becomes `HOLDOUT_PASSED` when `holdout_mape_pct` is at most 12.00 and `HOLDOUT_FAILED` when it is above 12.00."

    Design: Corner/calculations/holdout_backtest_predicts_the_held_out_period
    """
    ctx = fixtures.fitted_run(api, carryover_attribution_mode="EFFECT_PERIOD")
    baseline_before = ctx["run"]["baseline_sales_units"]

    validated = validate_success(
        api.validate_model_run(ctx["run"]["id"], test_users.MODELER)
    )
    assertions.assert_percentage(validated["holdout_mape_pct"], "holdout_mape_pct")
    assert _dec(validated["holdout_mape_pct"]) == _dec(
        fixtures.F1_EFFECT_HOLDOUT_MAPE_PCT
    ), (
        "the prediction for 2026-08-24 is the per-period baseline plus the two "
        "channel terms, each rounded to four decimals before being added, "
        f"scored against an actual of {fixtures.F1_HOLDOUT_ACTUAL_UNITS} units; got "
        f"{validated['holdout_mape_pct']}"
    )
    assert validated["validation_status"] == "HOLDOUT_PASSED", (
        "11.53 is at or below the 12.00 acceptance ceiling, so the branch taken "
        f"is HOLDOUT_PASSED; got {validated['validation_status']}"
    )

    assert validated["fit_status"] == "FITTED", (
        "validation reads the fit rather than refitting it; got "
        f"{validated['fit_status']}"
    )
    assert _dec(validated["baseline_sales_units"]) == _dec(baseline_before), (
        "the backtest must not move the fitted baseline; it went from "
        f"{baseline_before} to {validated['baseline_sales_units']}"
    )
    assert _dec(validated["baseline_sales_units"]) == _dec(
        fixtures.F1_EFFECT_BASELINE_UNITS
    ), validated["baseline_sales_units"]

    rows = fixtures.contributions_of(api, ctx["run"]["id"])
    assert len(rows) == 2, f"the two decomposition rows survive validation, got {len(rows)}"
    for row in rows:
        assert row["is_current"] is True, row


def test_interval_half_width_is_shared_and_scales_each_contribution(api):
    """PRD §3.4: "`ci_half_width_pct` is 40.0 divided by the square root of the run's `observation_period_count`, rounded half-up to two decimal places; it is therefore identical for every channel of a run."
    PRD §3.4: "`ci_low_units` is `contribution_units` multiplied by one minus one-hundredth of `ci_half_width_pct`, rounded half-up to four decimals, and `ci_high_units` is `contribution_units` multiplied by one plus one-hundredth of `ci_half_width_pct`, rounded half-up to four decimals."

    Design: Corner/calculations/contribution_confidence_interval_half_width_and_bounds
    """
    ctx = fixtures.fitted_run(api, carryover_attribution_mode="EFFECT_PERIOD")
    run = validate_success(api.get_model_run(ctx["run"]["id"], test_users.AUDITOR))
    assert run["observation_period_count"] == fixtures.F1_OBSERVATION_PERIOD_COUNT, run

    rows = _by_channel(fixtures.contributions_of(api, ctx["run"]["id"]))
    a_search = rows[ctx["a_search"]["id"]]
    b_social = rows[ctx["b_social"]["id"]]

    for channel_code, row in (("A_SEARCH", a_search), ("B_SOCIAL", b_social)):
        assertions.assert_channel_contribution(row)
        assertions.assert_percentage(row["ci_half_width_pct"], "ci_half_width_pct")
        assert _dec(row["ci_half_width_pct"]) == _dec(fixtures.F1_CI_HALF_WIDTH_PCT), (
            "the half-width depends only on the four observed periods, so both "
            f"channels share it; {channel_code} reported "
            f"{row['ci_half_width_pct']}"
        )

    assert _dec(a_search["ci_low_units"]) == _dec(fixtures.F1_EFFECT_CI_LOW_A_SEARCH), (
        f"A_SEARCH low bound scales {a_search['contribution_units']} down by the "
        f"shared half-width; got {a_search['ci_low_units']}"
    )
    assert _dec(a_search["ci_high_units"]) == _dec(
        fixtures.F1_EFFECT_CI_HIGH_A_SEARCH
    ), a_search["ci_high_units"]
    assert _dec(b_social["ci_low_units"]) == _dec(_B_SOCIAL_CI_LOW_UNITS), (
        f"B_SOCIAL low bound scales {b_social['contribution_units']} down by the "
        f"same half-width; got {b_social['ci_low_units']}"
    )
    assert _dec(b_social["ci_high_units"]) == _dec(_B_SOCIAL_CI_HIGH_UNITS), b_social[
        "ci_high_units"
    ]

    for row in (a_search, b_social):
        assertions.assert_unit_quantity(row["ci_low_units"], "ci_low_units")
        assertions.assert_unit_quantity(row["ci_high_units"], "ci_high_units")
        assert _dec(row["ci_low_units"]) < _dec(row["contribution_units"]) < _dec(
            row["ci_high_units"]
        ), row


def test_average_and_marginal_returns_are_two_different_rates(api):
    """PRD §3.4: "`attributed_spend_cents` is the sum of `spend_cents` over that channel's non-superseded spend observations inside the training window — raw spend, never the adstocked figure."
    PRD §3.4: "`contribution_revenue_cents` is `contribution_units` multiplied by the run's `unit_price_cents`, rounded half-up to a whole cent."
    PRD §3.4: "`average_roi` is `contribution_revenue_cents` divided by `attributed_spend_cents`, rounded half-up to four decimal places, and is reported as exactly 0.0000 when `attributed_spend_cents` is zero rather than being left undefined."
    PRD §3.4: "It is the run's `unit_price_cents` multiplied by the channel's `response_ceiling_units`, multiplied by the channel's `saturation_half_point_cents`, divided by the square of the quantity formed by adding `mean_adstocked_spend_cents` to `saturation_half_point_cents`, rounded half-up to six decimal places."

    Design: Corner/calculations/average_and_marginal_roi_are_distinct_rates
    """
    ctx = fixtures.fitted_run(api, carryover_attribution_mode="EFFECT_PERIOD")
    rows = _by_channel(fixtures.contributions_of(api, ctx["run"]["id"]))
    a_search = rows[ctx["a_search"]["id"]]
    b_social = rows[ctx["b_social"]["id"]]

    assert a_search["attributed_spend_cents"] == fixtures.F1_ATTRIBUTED_SPEND_A_SEARCH, (
        "the spend denominator is the raw weekly spend of the window, not the "
        f"adstocked series; got {a_search['attributed_spend_cents']}"
    )
    assert b_social["attributed_spend_cents"] == fixtures.F1_ATTRIBUTED_SPEND_B_SOCIAL, (
        b_social["attributed_spend_cents"]
    )

    assert a_search["contribution_revenue_cents"] == fixtures.F1_EFFECT_REVENUE_A_SEARCH, (
        f"{a_search['contribution_units']} units priced at "
        f"{fixtures.F1_UNIT_PRICE_CENTS} cents each; got "
        f"{a_search['contribution_revenue_cents']}"
    )
    assert b_social["contribution_revenue_cents"] == fixtures.F1_EFFECT_REVENUE_B_SOCIAL, (
        b_social["contribution_revenue_cents"]
    )
    assertions.assert_cents(
        a_search["contribution_revenue_cents"], "contribution_revenue_cents"
    )
    assertions.assert_cents(
        b_social["contribution_revenue_cents"], "contribution_revenue_cents"
    )

    assert _dec(a_search["average_roi"]) == _dec(
        fixtures.F1_EFFECT_AVERAGE_ROI_A_SEARCH
    ), (
        "average return is revenue over raw spend at four decimals; got "
        f"{a_search['average_roi']}"
    )
    assert _dec(b_social["average_roi"]) == _dec(
        fixtures.F1_EFFECT_AVERAGE_ROI_B_SOCIAL
    ), b_social["average_roi"]
    assertions.assert_decimal_places(a_search["average_roi"], 4, "average_roi")
    assertions.assert_decimal_places(b_social["average_roi"], 4, "average_roi")

    assert _dec(a_search["mean_adstocked_spend_cents"]) == _dec(
        fixtures.F1_EFFECT_MEAN_A_SEARCH
    ), a_search["mean_adstocked_spend_cents"]
    assert _dec(a_search["marginal_roi"]) == _dec(
        fixtures.F1_EFFECT_MARGINAL_ROI_A_SEARCH
    ), (
        "marginal return is evaluated at the mean of the adstocked series with "
        f"six decimals; got {a_search['marginal_roi']}"
    )
    assert _dec(b_social["marginal_roi"]) == _dec(
        fixtures.F1_EFFECT_MARGINAL_ROI_B_SOCIAL
    ), b_social["marginal_roi"]
    assertions.assert_decimal_places(a_search["marginal_roi"], 6, "marginal_roi")
    assertions.assert_decimal_places(b_social["marginal_roi"], 6, "marginal_roi")

    assert _dec(a_search["average_roi"]) != _dec(a_search["marginal_roi"]), a_search
    assert _dec(b_social["average_roi"]) != _dec(b_social["marginal_roi"]), b_social
    assert _dec(a_search["average_roi"]) < _dec(b_social["average_roi"]), (
        "B_SOCIAL wins on average return while A_SEARCH loses it, so the two "
        "rates rank the channels differently"
    )
    assert _dec(a_search["marginal_roi"]) < _dec(b_social["marginal_roi"]), (
        a_search["marginal_roi"],
        b_social["marginal_roi"],
    )


def test_a_binding_bound_stops_the_waterfall_and_is_stamped_on_the_row(api):
    """PRD §3.8: "Then, while the remaining budget is at least one hundred thousand cents — a one-thousand-unit-of-currency marginal step — the walk forms a candidate set of the channels for which adding one more step would keep the allocation at or below the channel's `max_spend_cents`."
    PRD §3.8: "The pass-one churn is the sum, across channels, of the absolute difference between each channel's pass-one allocation and its `baseline_spend_cents`, and `reallocation_fee_cents` is that churn multiplied by `reallocation_fee_pct`, divided by one hundred, rounded half-up to a whole cent."
    PRD §3.8: "Critically, the fee is **pinned at its pass-one value** and is not recomputed from pass two's smaller churn: the fee prices the plan the optimizer first proposed, and recomputing it would make the two passes chase each other without converging."
    PRD §3.8: "Each allocation row's `allocated_cents` becomes its pass-two figure; its `shifted_cents` becomes the absolute difference between that figure and its `baseline_spend_cents`; its `constraint_binding` becomes `FLOOR` when `allocated_cents` equals the channel's `min_spend_cents`, `CEILING` when it equals the channel's `max_spend_cents`, and `NONE` otherwise, with `FLOOR` winning when a channel's floor and ceiling are the same number; and its `projected_contribution_units` becomes the projection function evaluated at `allocated_cents`, rounded half-up to four decimal places."
    PRD §3.8: "On the scenario, `allocated_total_cents` is the sum of the rows' `allocated_cents`; `shifted_total_cents` is the sum of the rows' `shifted_cents`, which is the pass-two churn and is reporting only; `unallocated_cents` is `total_budget_cents` minus `reallocation_fee_cents` minus `allocated_total_cents`; `projected_contribution_units` is the sum of the rows' `projected_contribution_units`; and `projected_incremental_revenue_cents` is that total multiplied by the referenced run's `unit_price_cents`, rounded half-up to a whole cent."

    Design: Corner/calculations/budget_optimization_ceiling_and_floor_constraint_binding
    """
    ctx = fixtures.published_run(
        api, a_search_overrides={"max_spend_cents": _A_SEARCH_CAPPED_MAX_CENTS}
    )
    a_search_id = ctx["a_search"]["id"]
    b_social_id = ctx["b_social"]["id"]

    fixtures.scenario_with_allocations(api, ctx)
    capped = validate_success(
        api.optimize_budget_scenario(ctx["scenario"]["id"], test_users.BRAND_PLANNER)
    )
    assertions.assert_budget_scenario(capped)
    assert capped["status"] == "OPTIMIZED", capped["status"]
    assert capped["reallocation_fee_cents"] == _CEILING_FEE_CENTS, (
        "the fee prices pass one's churn, not pass two's; got "
        f"{capped['reallocation_fee_cents']}"
    )
    assert capped["allocated_total_cents"] == _CEILING_ALLOCATED_TOTAL_CENTS, capped[
        "allocated_total_cents"
    ]
    assert capped["unallocated_cents"] == _CEILING_UNALLOCATED_CENTS, (
        "with A_SEARCH out of the candidate set the last partial step cannot be "
        f"awarded and stays unspent; got {capped['unallocated_cents']}"
    )
    assert capped["shifted_total_cents"] == _CEILING_SHIFTED_TOTAL_CENTS, capped[
        "shifted_total_cents"
    ]
    assertions.assert_budget_conservation(capped)

    capped_rows = _by_channel(fixtures.allocations_of(api, ctx["scenario"]["id"]))
    capped_a = capped_rows[a_search_id]
    capped_b = capped_rows[b_social_id]
    assertions.assert_budget_allocation(capped_a)
    assertions.assert_budget_allocation(capped_b)
    assert capped_a["allocated_cents"] == _CEILING_A_SEARCH_ALLOCATED_CENTS, capped_a[
        "allocated_cents"
    ]
    assert capped_a["constraint_binding"] == "CEILING", (
        "A_SEARCH landed exactly on its max_spend_cents, so the reason is "
        f"stamped as CEILING; got {capped_a['constraint_binding']}"
    )
    assert capped_a["shifted_cents"] == _CEILING_SHIFTED_A_SEARCH_CENTS, capped_a[
        "shifted_cents"
    ]
    assert capped_b["allocated_cents"] == _CEILING_B_SOCIAL_ALLOCATED_CENTS, capped_b[
        "allocated_cents"
    ]
    assert capped_b["constraint_binding"] == "NONE", (
        "B_SOCIAL absorbed the spill without touching either of its own bounds; "
        f"got {capped_b['constraint_binding']}"
    )
    assert capped_b["shifted_cents"] == _CEILING_SHIFTED_B_SOCIAL_CENTS, capped_b[
        "shifted_cents"
    ]

    validate_success(
        api.patch_media_channel(
            a_search_id,
            {"max_spend_cents": _A_SEARCH_RESTORED_MAX_CENTS},
            test_users.DATA_ENGINEER,
        )
    )
    validate_success(
        api.patch_media_channel(
            b_social_id,
            {"min_spend_cents": _B_SOCIAL_RAISED_MIN_CENTS},
            test_users.DATA_ENGINEER,
        )
    )

    fixtures.scenario_with_allocations(api, ctx)
    floored = validate_success(
        api.optimize_budget_scenario(ctx["scenario"]["id"], test_users.BRAND_PLANNER)
    )
    assert floored["reallocation_fee_cents"] == _FLOOR_FEE_CENTS, (
        "pass one churned a different amount under the raised floor, so the "
        f"pinned fee differs from the capped run's; got "
        f"{floored['reallocation_fee_cents']}"
    )
    assert floored["reallocation_fee_cents"] != capped["reallocation_fee_cents"], (
        capped["reallocation_fee_cents"],
        floored["reallocation_fee_cents"],
    )
    assert floored["allocated_total_cents"] == _FLOOR_ALLOCATED_TOTAL_CENTS, floored[
        "allocated_total_cents"
    ]
    assert floored["unallocated_cents"] == _FLOOR_UNALLOCATED_CENTS, floored[
        "unallocated_cents"
    ]
    assert floored["shifted_total_cents"] == _FLOOR_SHIFTED_TOTAL_CENTS, floored[
        "shifted_total_cents"
    ]
    assertions.assert_budget_conservation(floored)

    floored_rows = _by_channel(fixtures.allocations_of(api, ctx["scenario"]["id"]))
    floored_a = floored_rows[a_search_id]
    floored_b = floored_rows[b_social_id]
    assert floored_b["allocated_cents"] == _FLOOR_B_SOCIAL_ALLOCATED_CENTS, floored_b[
        "allocated_cents"
    ]
    assert floored_b["constraint_binding"] == "FLOOR", (
        "B_SOCIAL never won a step, so it sits on the seed the walk gave it and "
        f"the reason is FLOOR; got {floored_b['constraint_binding']}"
    )
    assert floored_b["shifted_cents"] == _FLOOR_SHIFTED_B_SOCIAL_CENTS, floored_b[
        "shifted_cents"
    ]
    assert floored_a["allocated_cents"] == _FLOOR_A_SEARCH_ALLOCATED_CENTS, floored_a[
        "allocated_cents"
    ]
    assert floored_a["constraint_binding"] == "NONE", floored_a["constraint_binding"]
    assert floored_a["shifted_cents"] == _FLOOR_SHIFTED_A_SEARCH_CENTS, floored_a[
        "shifted_cents"
    ]


def test_stability_floor_gates_the_refresh_until_the_override_is_sent(api):
    """PRD §3.5: "When an incumbent exists, the comparison runs over the **union** of the two runs' channels, taken in ascending `channel_code` order, using only decomposition rows whose `is_current` is true, and a channel that appears in one run but not the other contributes an `average_roi` of 0 for the run it is missing from."
    PRD §3.5: "A drift total is formed as the sum, across that union, of the absolute difference between the candidate's `average_roi` and the incumbent's `average_roi` for that channel."
    PRD §3.5: "A base total is formed as the sum of the incumbent's `average_roi` values across the incumbent's own channels."
    PRD §3.5: "`stability_score` is then one minus the drift total divided by the base total, floored at zero so it never goes negative, rounded half-up to four decimal places; and `refresh_generation` is the incumbent's `refresh_generation` plus one."
    PRD §3.5: "If `stability_score` falls below 0.6000 the publication is refused with `ERR_MODEL_UNSTABLE`, unless the request body carries `override_stability` set to true — the single privilege that lets an `AnalyticsLead` publish through a stability breach, and the only route past that error."
    PRD §3.5: "The union rule has a deliberate consequence worth internalising: dropping a channel from the specification is penalised far harder than changing the attribution mode, because a dropped channel's ROI falls all the way to zero inside the union while a re-decomposed channel's ROI merely moves."

    Design: Corner/calculations/refresh_stability_floor_constant_applied_with_override
    """
    ctx = fixtures.published_run(api)
    incumbent_id = ctx["run"]["id"]
    incumbent = validate_success(
        api.get_model_run(incumbent_id, test_users.AUDITOR)
    )
    assert incumbent["refresh_generation"] == _FIRST_REFRESH_GENERATION, (
        "the market's first publication is generation one and skips the gate "
        f"entirely; got {incumbent['refresh_generation']}"
    )
    assert incumbent["previous_published_run_id"] is None, incumbent[
        "previous_published_run_id"
    ]
    assert _dec(incumbent["holdout_mape_pct"]) == _dec(
        fixtures.F1_EFFECT_HOLDOUT_MAPE_PCT
    ), incumbent["holdout_mape_pct"]

    candidate = fixtures.create_run(
        api, ctx, included_channel_ids=[ctx["a_search"]["id"]]
    )
    validate_success(api.fit_model_run(candidate["id"], test_users.MODELER))
    validated = validate_success(
        api.validate_model_run(candidate["id"], test_users.MODELER)
    )
    assert validated["validation_status"] == "HOLDOUT_PASSED", validated[
        "validation_status"
    ]
    assert _dec(validated["holdout_mape_pct"]) == _dec(
        _A_SEARCH_ONLY_HOLDOUT_MAPE_PCT
    ), (
        "the A_SEARCH-only refit clears its own backtest, so the only thing that "
        f"can block it is stability; got {validated['holdout_mape_pct']}"
    )

    refused = api.publish_model_run(
        candidate["id"], test_users.ANALYTICS_LEAD, factories.publish_payload()
    )
    validate_error(refused, "ERR_MODEL_UNSTABLE", 422)
    blocked = validate_success(api.get_model_run(candidate["id"], test_users.AUDITOR))
    assert blocked["publication_status"] == "UNPUBLISHED", (
        "the refused publication leaves the candidate exactly where it was; got "
        f"{blocked['publication_status']}"
    )
    still_incumbent = validate_success(
        api.get_model_run(incumbent_id, test_users.AUDITOR)
    )
    assert still_incumbent["publication_status"] == "PUBLISHED", still_incumbent[
        "publication_status"
    ]

    overridden = validate_success(
        api.publish_model_run(
            candidate["id"],
            test_users.ANALYTICS_LEAD,
            factories.publish_payload(True),
        )
    )
    assert overridden["publication_status"] == "PUBLISHED", overridden[
        "publication_status"
    ]
    assert _dec(overridden["stability_score"]) == _dec(
        _A_SEARCH_ONLY_STABILITY_SCORE
    ), (
        "dropping B_SOCIAL sends its return to zero inside the union, and the "
        "override suppresses the gate without suppressing the score; got "
        f"{overridden['stability_score']}"
    )
    assertions.assert_decimal_places(
        overridden["stability_score"], 4, "stability_score"
    )
    assert _dec(overridden["stability_score"]) < _dec(0.6000), overridden[
        "stability_score"
    ]
    assert overridden["refresh_generation"] == _SECOND_REFRESH_GENERATION, overridden[
        "refresh_generation"
    ]
    assert overridden["previous_published_run_id"] == incumbent_id, overridden[
        "previous_published_run_id"
    ]

    superseded = validate_success(
        api.get_model_run(incumbent_id, test_users.AUDITOR)
    )
    assert superseded["publication_status"] == "SUPERSEDED", superseded[
        "publication_status"
    ]


def test_each_derived_figure_carries_its_own_declared_precision(api):
    """PRD §2.6: "Monetary amounts are integer cents throughout; there is no fractional cent anywhere in the system, and every cent-valued computed field is rounded half-up to a whole cent."
    PRD §2.6: "Contribution and projection quantities expressed in sales units carry four decimal places."
    PRD §2.6: "Percentages — holdout share, lag completeness, holdout error, measured lift and its interval, per-line and weighted variance — carry two decimal places."
    PRD §2.6: "Average return on investment, calibration multipliers, stability scores and the experiment power quantities carry four decimal places."
    PRD §2.6: "Marginal return on investment carries six decimal places, and the synthetic-control weight carries six decimal places."
    PRD §3.4: "The channel's `contribution_units` is then the exact sum of those per-period values across the whole window, rounded half-up to four decimal places **once**, over the exact sum."
    PRD §3.4: "The per-period terms are deliberately not pre-rounded here; rounding each period first and summing afterwards is a different number and is not what this rule specifies."

    Design: Corner/calculations/contribution_precision_declared_decimal_places
    """
    ctx = fixtures.fitted_run(api, carryover_attribution_mode="EFFECT_PERIOD")
    run = validate_success(api.get_model_run(ctx["run"]["id"], test_users.AUDITOR))
    rows = _by_channel(fixtures.contributions_of(api, ctx["run"]["id"]))
    a_search = rows[ctx["a_search"]["id"]]
    b_social = rows[ctx["b_social"]["id"]]

    assert _dec(b_social["contribution_units"]) == _dec(
        fixtures.F1_EFFECT_CONTRIBUTION_B_SOCIAL
    ), (
        "the four per-period unit terms are summed exactly and rounded only "
        f"once at the end; got {b_social['contribution_units']}"
    )
    assert _dec(b_social["contribution_units"]) != _dec(
        _FORBIDDEN_PRE_ROUNDED_B_SOCIAL_UNITS
    ), (
        "rounding each period to four decimals before summing lands one "
        "ten-thousandth higher, which is a different number and is not the rule"
    )
    assert _dec(a_search["contribution_units"]) == _dec(
        fixtures.F1_EFFECT_CONTRIBUTION_A_SEARCH
    ), a_search["contribution_units"]
    assertions.assert_unit_quantity(
        a_search["contribution_units"], "contribution_units"
    )
    assertions.assert_unit_quantity(
        b_social["contribution_units"], "contribution_units"
    )

    assert _dec(run["baseline_sales_units"]) == _dec(
        fixtures.F1_EFFECT_BASELINE_UNITS
    ), run["baseline_sales_units"]
    assertions.assert_decimal_places(
        run["baseline_sales_units"], 4, "baseline_sales_units"
    )

    assertions.assert_decimal_places(a_search["average_roi"], 4, "average_roi")
    assertions.assert_decimal_places(b_social["average_roi"], 4, "average_roi")
    assertions.assert_decimal_places(a_search["marginal_roi"], 6, "marginal_roi")
    assertions.assert_decimal_places(b_social["marginal_roi"], 6, "marginal_roi")
    assert _dec(a_search["average_roi"]) == _dec(
        fixtures.F1_EFFECT_AVERAGE_ROI_A_SEARCH
    ), a_search["average_roi"]
    assert _dec(a_search["marginal_roi"]) == _dec(
        fixtures.F1_EFFECT_MARGINAL_ROI_A_SEARCH
    ), a_search["marginal_roi"]

    assert a_search["contribution_revenue_cents"] == fixtures.F1_EFFECT_REVENUE_A_SEARCH, (
        a_search["contribution_revenue_cents"]
    )
    assert isinstance(a_search["contribution_revenue_cents"], int), (
        "revenue is a whole number of cents, never a fraction of one; got "
        f"{a_search['contribution_revenue_cents']!r}"
    )
    assert run["unit_price_cents"] == fixtures.F1_UNIT_PRICE_CENTS, run[
        "unit_price_cents"
    ]
    assert isinstance(run["unit_price_cents"], int), repr(run["unit_price_cents"])

    assert a_search["mean_adstocked_spend_cents"] == fixtures.F1_EFFECT_MEAN_A_SEARCH, (
        a_search["mean_adstocked_spend_cents"]
    )
    assert isinstance(a_search["mean_adstocked_spend_cents"], int), repr(
        a_search["mean_adstocked_spend_cents"]
    )
    assert all(
        isinstance(value, int) for value in a_search["adstocked_spend_series"]
    ), a_search["adstocked_spend_series"]

    assert _dec(a_search["ci_half_width_pct"]) == _dec(fixtures.F1_CI_HALF_WIDTH_PCT), (
        a_search["ci_half_width_pct"]
    )
    assertions.assert_decimal_places(
        a_search["ci_half_width_pct"], 2, "ci_half_width_pct"
    )
