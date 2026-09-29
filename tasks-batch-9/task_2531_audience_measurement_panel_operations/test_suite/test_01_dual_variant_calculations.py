"""The two calculations that exist in two variants at once.

Weighting runs under a `DESIGN` or a `FINAL` variant that differ only in the
denominator of the base weight, and compliance is scored both as a rolling
30-day panel-health monitor and as a run-scoped figure on every weight row.
This file pins both pairs apart on the same data, so a single implementation
that collapses either pair into one formula fails here.
"""

from test_helpers.assertions import (
    expected_base_weight,
    expected_compliance_rate,
    expected_contribution,
    expected_projected_average_audience,
    expected_run_evaluated_days,
)
from test_helpers.factories import cell_population
from test_helpers.fixtures import CLOCK_T1, WINDOW_MINUTES, PanelHarness

# The design index's rule set: nothing here invalidates the blocks below, the
# ascription allowance never spans the gap between them, and the ratio cap of
# 2.5 leaves both variants uncapped so the denominators are the only difference.
RECIPE_RULE_SET = {
    "missing_interval_ascription_minutes": 60,
    "invalid_tuning_max_minutes": 900,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.5,
    "fault_missing_minutes_threshold": 1440,
}

CELL_A_SPEC = {
    "age_band": "P18_34",
    "income_band": "MID",
    "geo_zone": "URBAN",
    "target_households": 3,
    "base_incentive_cents": 2000,
}
CELL_B_SPEC = {
    "age_band": "P35_54",
    "income_band": "HIGH",
    "geo_zone": "SUBURBAN",
    "target_households": 1,
    "base_incentive_cents": 3000,
}


def _dual_variant_panel(panel: PanelHarness) -> dict:
    """Two cells of 120000 and 80000 households, three homes, one EDITED run.

    Cell A holds one `ACTIVE` home that contributes 350 minutes plus one home
    left standing in `RECRUITED` that never delivers anything; cell B holds one
    `ACTIVE` home that contributes 730 minutes. The `FINAL` denominator of cell
    A is therefore 1 while its `DESIGN` denominator is 2, and cell B's is 1
    under both variants.
    """
    market, cells = panel.market_with_cells(
        [CELL_A_SPEC, CELL_B_SPEC], incentive_budget_cents=1000000
    )
    rule_set = panel.published_rule_set(**RECIPE_RULE_SET)
    universe = panel.published_universe(
        market["id"],
        [cell["id"] for cell in cells],
        cell_populations=[
            cell_population(cells[0]["id"], 120000, 300000),
            cell_population(cells[1]["id"], 80000, 160000),
        ],
    )
    home_a = panel.active_household(market["id"], cells[0]["id"], persons_count=2)
    home_b = panel.active_household(market["id"], cells[1]["id"], persons_count=2)
    recruited_only = panel.recruit_household(
        market["id"], cells[0]["id"], recruitment_source="ONLINE_PANEL_TRANSFER", persons_count=2
    )
    panel.set_clock(CLOCK_T1)
    panel.ingest_interval(
        home_a["tuner"]["id"],
        home_a["household"]["id"],
        "2026-08-01T18:00:00Z",
        "2026-08-01T23:50:00Z",
        350,
    )
    panel.ingest_interval(
        home_b["tuner"]["id"],
        home_b["household"]["id"],
        "2026-08-01T06:00:00Z",
        "2026-08-01T18:10:00Z",
        730,
    )
    run = panel.open_run(market["id"], universe["id"], rule_set["id"])
    run = panel.edit_run(run["id"])
    return {
        "market": market,
        "cells": cells,
        "rule_set": rule_set,
        "universe": universe,
        "home_a": home_a["household"],
        "home_b": home_b["household"],
        "recruited_only": recruited_only,
        "run": run,
    }


class TestDesignVersusFinalWeighting:
    """One EDITED run weighted both ways, on data that separates the variants."""

    def test_final_denominator_counts_only_this_run_s_contributors(
        self, panel: PanelHarness
    ):
        """The FINAL variant divides each cell population by its contributors alone.

        PRD 3.7: "Under `FINAL`, the denominator is the number of households of
        that cell that actually contributed at least one `EDITED` or `ASCRIBED`
        interval to **this** run with `usable_minutes` above 0."

        Design: Difficulty/dual_variant_calc/design_vs_final_weighting_diverge_on_one_edited_run
        """
        built = _dual_variant_panel(panel)
        assert built["run"]["contributing_household_count"] == 2

        run = panel.weight_run(built["run"]["id"], weight_variant="FINAL")

        assert run["state"] == "WEIGHTED"
        assert run["weight_variant"] == "FINAL"
        rows = panel.weights_of_run(run["id"])
        assert len(rows) == 2
        by_household = {row["household_id"]: row for row in rows}
        row_a = by_household[built["home_a"]["id"]]
        row_b = by_household[built["home_b"]["id"]]

        # Cell A: 120000 over its single contributor, not over its two recruits.
        assert row_a["base_weight"] == 120000.0000 == expected_base_weight(120000, 1)
        assert row_a["adjusted_weight"] == 120000.0000
        assert row_a["capped"] is False
        assert row_a["usable_minutes"] == 350
        assert row_b["base_weight"] == 80000.0000 == expected_base_weight(80000, 1)
        assert row_b["usable_minutes"] == 730

        # 120000 * 350 / 1440 and 80000 * 730 / 1440, each to 2 decimal places.
        assert row_a["contribution"] == 29166.67
        assert row_a["contribution"] == expected_contribution(120000.0, 350, WINDOW_MINUTES)
        assert row_b["contribution"] == 40555.56
        assert row_b["contribution"] == expected_contribution(80000.0, 730, WINDOW_MINUTES)

        assert run["total_weight_mass"] == 200000.0000
        assert run["projected_average_audience"] == 69722
        assert run["projected_average_audience"] == expected_projected_average_audience(
            [29166.67, 40555.56]
        )
        assert run["excluded_cell_count"] == 0

    def test_design_denominator_counts_every_non_retired_recruit(self, panel: PanelHarness):
        """Re-weighting under DESIGN halves cell A's base weight on the same data.

        PRD 3.7: "Under `DESIGN`, the denominator is the number of households of
        that cell whose `status` is `RECRUITED`, `INSTALL_SCHEDULED`,
        `ENUM_PENDING`, `ACTIVE`, `FAULT_HOLD` or `NONCOMPLIANT_HOLD` — every
        non-retired recruit counts, whether or not it delivered any data."

        Design: Difficulty/dual_variant_calc/design_vs_final_weighting_diverge_on_one_edited_run
        """
        built = _dual_variant_panel(panel)
        panel.weight_run(built["run"]["id"], weight_variant="FINAL")

        run = panel.weight_run(built["run"]["id"], weight_variant="DESIGN")

        assert run["state"] == "WEIGHTED"
        assert run["weight_variant"] == "DESIGN"
        rows = panel.weights_of_run(run["id"])
        # PRD 3.7: "Every existing weight row of the run is deleted first" - the
        # re-weight replaces the two FINAL rows rather than appending to them.
        assert len(rows) == 2
        assert all(row["weight_variant"] == "DESIGN" for row in rows)
        by_household = {row["household_id"]: row for row in rows}
        row_a = by_household[built["home_a"]["id"]]
        row_b = by_household[built["home_b"]["id"]]

        # Cell A now divides 120000 by the ACTIVE home plus the RECRUITED one.
        assert row_a["base_weight"] == 60000.0000 == expected_base_weight(120000, 2)
        assert row_a["adjusted_weight"] == 60000.0000
        assert row_a["capped"] is False
        assert row_b["base_weight"] == 80000.0000 == expected_base_weight(80000, 1)

        assert row_a["contribution"] == 14583.33
        assert row_a["contribution"] == expected_contribution(60000.0, 350, WINDOW_MINUTES)
        assert row_b["contribution"] == 40555.56

        assert run["total_weight_mass"] == 140000.0000
        assert run["projected_average_audience"] == 55139
        assert run["projected_average_audience"] == expected_projected_average_audience(
            [14583.33, 40555.56]
        )
        # The home that never delivered data still has no weight row of its own.
        assert built["recruited_only"]["id"] not in by_household
        assert panel.read_household(built["recruited_only"]["id"])["status"] == "RECRUITED"

    def test_the_two_variants_diverge_by_the_recruited_only_household(
        self, panel: PanelHarness
    ):
        """The same window projects 69722 under FINAL and 55139 under DESIGN.

        PRD 3.7: "The two variants differ *only* in the denominator, and the
        difference is the whole methodological point".

        Design: Difficulty/dual_variant_calc/design_vs_final_weighting_diverge_on_one_edited_run
        """
        built = _dual_variant_panel(panel)

        final_run = panel.weight_run(built["run"]["id"], weight_variant="FINAL")
        final_projection = final_run["projected_average_audience"]
        final_mass = final_run["total_weight_mass"]

        design_run = panel.weight_run(built["run"]["id"], weight_variant="DESIGN")

        assert final_projection == 69722
        assert design_run["projected_average_audience"] == 55139
        assert final_projection - design_run["projected_average_audience"] == 14583
        assert final_mass == 200000.0000
        assert design_run["total_weight_mass"] == 140000.0000
        # PRD 3.7 re-weighting: the two figures are overwritten, not accumulated.
        assert panel.read_run(built["run"]["id"])["total_weight_mass"] == 140000.0000


def _compliance_panel(panel: PanelHarness) -> dict:
    """One home reporting 10 minutes on 2026-07-31 and 350 on 2026-08-01.

    Only the second block lies inside the 2026-08-01/2026-08-02 run window, so
    the rolling monitor scores the home out of two reported days while the run
    scores it out of the single calendar day of the window.
    """
    market, cells = panel.market_with_cells(
        [{"target_households": 1, "base_incentive_cents": 2000}], incentive_budget_cents=1000000
    )
    rule_set = panel.published_rule_set(**RECIPE_RULE_SET)
    universe = panel.published_universe(
        market["id"],
        [cells[0]["id"]],
        cell_populations=[cell_population(cells[0]["id"], 120000, 300000)],
    )
    home = panel.active_household(market["id"], cells[0]["id"], persons_count=2)
    panel.set_clock(CLOCK_T1)
    short_block = panel.ingest_interval(
        home["tuner"]["id"],
        home["household"]["id"],
        "2026-07-31T20:00:00Z",
        "2026-07-31T20:10:00Z",
        10,
    )
    long_block = panel.ingest_interval(
        home["tuner"]["id"],
        home["household"]["id"],
        "2026-08-01T18:00:00Z",
        "2026-08-01T23:50:00Z",
        350,
    )
    return {
        "market": market,
        "cells": cells,
        "rule_set": rule_set,
        "universe": universe,
        "household": home["household"],
        "tuner": home["tuner"],
        "short_block": short_block,
        "long_block": long_block,
    }


class TestRollingVersusRunScopedCompliance:
    """The same two blocks score 0.5000 rolling and 1.0000 run-scoped."""

    def test_rolling_rate_scores_reported_days_only_from_raw_minutes(
        self, panel: PanelHarness
    ):
        """Two reported days, one of them short, give a rolling rate of 0.5000.

        PRD 3.6: "The evaluated days are the count of distinct UTC calendar dates
        inside that window on which the household holds at least one interval in
        `state` `RAW`, `EDITED` or `ASCRIBED` — **reported days only**, so a
        household that reported on two days out of the thirty is scored out of 2
        and not out of 30."

        Design: Difficulty/dual_variant_calc/compliance_rolling_30_vs_run_scoped_diverge_for_one_household
        """
        built = _compliance_panel(panel)

        household = panel.read_household(built["household"]["id"])

        # 2026-07-31 reported 10 raw minutes and fails the 30-minute test;
        # 2026-08-01 reported 350 and passes. One compliant day out of two.
        assert household["compliance_rate_rolling_30"] == 0.5000
        assert household["compliance_rate_rolling_30"] == expected_compliance_rate(1, 2)
        assert panel.read_interval(built["short_block"]["id"])["state"] == "RAW"
        assert panel.read_interval(built["long_block"]["id"])["state"] == "RAW"

    def test_run_scoped_rate_scores_every_window_day_from_edited_minutes(
        self, panel: PanelHarness
    ):
        """The run window's single day is fully compliant, so the row reads 1.0000.

        PRD 3.7: "Its evaluated days are **every** calendar day of the run window
        — the run's `window_minutes` divided by 1440 and rounded up — whether the
        household reported on that day or not".

        Design: Difficulty/dual_variant_calc/compliance_rolling_30_vs_run_scoped_diverge_for_one_household
        """
        built = _compliance_panel(panel)
        run = panel.open_run(
            built["market"]["id"], built["universe"]["id"], built["rule_set"]["id"]
        )
        run = panel.edit_run(run["id"])

        run = panel.weight_run(run["id"], weight_variant="FINAL")

        assert run["window_minutes"] == WINDOW_MINUTES
        assert expected_run_evaluated_days(WINDOW_MINUTES) == 1
        rows = panel.weights_of_run(run["id"], household_id=built["household"]["id"])
        assert len(rows) == 1
        row = rows[0]
        assert row["usable_minutes"] == 350
        assert row["run_compliance_rate"] == 1.0000
        assert row["run_compliance_rate"] == expected_compliance_rate(1, 1)
        assert row["base_weight"] == 120000.0000
        assert row["contribution"] == 29166.67
        assert run["projected_average_audience"] == 29167
        assert run["total_weight_mass"] == 120000.0000

        # The out-of-window block was never claimed, and the rolling snapshot the
        # last ingest computed is not rewritten by the weighting pass.
        short = panel.read_interval(built["short_block"]["id"])
        assert short["state"] == "RAW"
        assert short["processing_run_id"] is None
        assert short["usable_minutes"] == 0
        long_block = panel.read_interval(built["long_block"]["id"])
        assert long_block["state"] == "EDITED"
        assert long_block["usable_minutes"] == 350
        assert panel.read_household(built["household"]["id"])["compliance_rate_rolling_30"] == 0.5000
