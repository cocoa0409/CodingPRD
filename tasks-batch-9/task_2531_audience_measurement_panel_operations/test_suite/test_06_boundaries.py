"""Boundary precision: metrics sitting exactly on a threshold, and one unit off.

Three different metrics on three different endpoints are pinned here - the
billing volume bracket on dispatch, the coverage shortfall on fault detection and
the run-relative weight cap on weighting - each with the at-the-boundary case
paired against the closest representable point on the other side of it.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers.factories import cell_population
from test_helpers.fixtures import PanelHarness

RULE_SET_THRESHOLDS = {
    "missing_interval_ascription_minutes": 60,
    "invalid_tuning_max_minutes": 900,
    "outlier_household_minutes_cap": 1200,
    "outlier_weight_ratio_cap": 2.5,
    "fault_missing_minutes_threshold": 1440,
}

WINDOW_0810_START = "2026-08-10T00:00:00Z"
WINDOW_0810_END = "2026-08-11T00:00:00Z"


def _measurement_base(
    panel: PanelHarness,
    *,
    name: str,
    market_code: str,
    dma_rank: int,
    cell_specs,
    populations,
    **rule_overrides,
):
    """A market, its cells, a PUBLISHED rule set and a PUBLISHED 2026Q3 vintage."""
    thresholds = dict(RULE_SET_THRESHOLDS)
    thresholds.update(rule_overrides)
    market = panel.create_market(
        name=name,
        market_code=market_code,
        dma_rank=dma_rank,
        incentive_budget_cents=1000000,
    )
    cells = [panel.create_quota_cell(market["id"], **spec) for spec in cell_specs]
    rule_set = panel.published_rule_set(label="RS-2026Q3", **thresholds)
    universe = panel.published_universe(
        market["id"],
        [cell["id"] for cell in cells],
        vintage_label="2026Q3",
        cell_populations=[
            cell_population(cell["id"], households, persons)
            for cell, (households, persons) in zip(cells, populations)
        ],
    )
    return {
        "market": market,
        "cells": cells,
        "rule_set": rule_set,
        "universe": universe,
    }


def _weights_of(panel: PanelHarness, run_id: str, household_id: str):
    """The single household-weight row of one run and one household."""
    rows, meta = validate_paginated(
        panel.client.list_household_weights(
            panel.statistician, processing_run_id=run_id, household_id=household_id
        )
    )
    assert meta["total_count"] == 1
    return rows[0]


def _weight_row_count(panel: PanelHarness, run_id: str) -> int:
    """How many household-weight rows the run carries."""
    _rows, meta = validate_paginated(
        panel.client.list_household_weights(
            panel.statistician, processing_run_id=run_id, limit=100
        )
    )
    return meta["total_count"]


def _dma_512_published_run_with_two_scheduled_rows(panel: PanelHarness):
    """DMA-512: a PUBLISHED run and a STANDARD client holding a 17- and a 16-cell row."""
    base = _measurement_base(
        panel,
        name="Metro Mu",
        market_code="DMA-512",
        dma_rank=12,
        cell_specs=[
            {
                "age_band": "P18_34",
                "income_band": "MID",
                "geo_zone": "URBAN",
                "target_households": 1,
                "base_incentive_cents": 2000,
            }
        ],
        populations=[(120000, 300000)],
    )
    built = panel.active_household(
        base["market"]["id"], base["cells"][0]["id"], persons_count=2
    )
    panel.set_clock("2026-08-11T00:00:00Z")
    panel.ingest_interval(
        built["tuner"]["id"],
        built["household"]["id"],
        "2026-08-10T18:00:00Z",
        "2026-08-10T23:50:00Z",
        350,
        station_code="WXYZ",
    )
    run = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso=WINDOW_0810_START,
        window_end_iso=WINDOW_0810_END,
    )
    panel.edit_run(run["id"])
    run = panel.weight_run(run["id"], weight_variant="FINAL")
    assert run["projected_average_audience"] == 29167

    subscriber = panel.create_client(
        [base["market"]["id"]], name="Mu Media Buying", tier="STANDARD"
    )
    row_17 = panel.schedule_deliverable(subscriber["id"], run["id"], requested_cell_count=17)
    row_16 = panel.schedule_deliverable(subscriber["id"], run["id"], requested_cell_count=16)
    assert row_17["due_at"] is None
    assert row_16["due_at"] is None

    panel.set_clock("2026-08-12T00:00:00Z")
    run = panel.publish_run(run["id"])
    assert run["state"] == "PUBLISHED"

    base["run"] = run
    base["subscriber"] = subscriber
    base["row_17"] = row_17
    base["row_16"] = row_16
    return base


class TestBillingVolumeBracketAtExactly150000Gross:
    """The volume-discount bracket floor of 150000 gross cents, on dispatch."""

    def test_gross_exactly_at_150000_takes_the_fifteen_percent_bracket(
        self, panel: PanelHarness
    ):
        """A 17-cell STANDARD dataset grosses exactly 150000 and discounts 22500.

        PRD 3.8: "The volume discount rate is 0.00 when `gross_cents` is below
        80000, 0.10 when it is at least 80000 but below 150000, and 0.15 when it is
        150000 or more."

        Design: Difficulty/boundary_precision_check/billing_volume_bracket_at_exactly_150000_gross
        """
        base = _dma_512_published_run_with_two_scheduled_rows(panel)

        delivered = validate_success(
            panel.client.dispatch_deliverable(panel.rep, base["row_17"]["id"]), 200
        )
        assert delivered["gross_cents"] == 150000
        assert delivered["discount_cents"] == 22500
        assert delivered["days_late"] == 0
        assert delivered["late_penalty_cents"] == 0
        assert delivered["total_cents"] == 127500
        assert delivered["state"] == "DELIVERED"
        assert delivered["kind"] == "SCHEDULED_DATASET"
        assert delivered["findings_summary"] is None

    def test_gross_one_bracket_step_below_the_floor_takes_ten_percent(
        self, panel: PanelHarness
    ):
        """A 16-cell dataset grosses 145000 - the closest point below - and discounts 14500.

        PRD 3.8: "The volume discount rate is 0.00 when `gross_cents` is below
        80000, 0.10 when it is at least 80000 but below 150000, and 0.15 when it is
        150000 or more."

        Design: Difficulty/boundary_precision_check/billing_volume_bracket_at_exactly_150000_gross
        """
        base = _dma_512_published_run_with_two_scheduled_rows(panel)

        delivered = validate_success(
            panel.client.dispatch_deliverable(panel.rep, base["row_16"]["id"]), 200
        )
        assert delivered["gross_cents"] == 145000
        assert delivered["discount_cents"] == 14500
        assert delivered["days_late"] == 0
        assert delivered["late_penalty_cents"] == 0
        assert delivered["total_cents"] == 130500

    def test_the_larger_dataset_bills_less_than_the_smaller_one(
        self, panel: PanelHarness
    ):
        """127500 against 130500: the higher gross pays less, only if 150000 is inclusive.

        PRD 3.8: "`total_cents` is `gross_cents` less `discount_cents` less
        `late_penalty_cents`, floored at 0."

        Design: Difficulty/boundary_precision_check/billing_volume_bracket_at_exactly_150000_gross
        """
        base = _dma_512_published_run_with_two_scheduled_rows(panel)

        bigger = validate_success(
            panel.client.dispatch_deliverable(panel.rep, base["row_17"]["id"]), 200
        )
        smaller = validate_success(
            panel.client.dispatch_deliverable(panel.rep, base["row_16"]["id"]), 200
        )
        assert bigger["gross_cents"] > smaller["gross_cents"]
        assert bigger["total_cents"] < smaller["total_cents"]
        assert panel.read_client(base["subscriber"]["id"])["delivery_sla_credit_cents"] == 0

    def test_publication_stamps_due_at_on_both_scheduled_rows(
        self, panel: PanelHarness
    ):
        """Rows placed before publication have no due date until the run publishes.

        PRD 3.7: "Finally, publication starts the commercial clock: every client
        deliverable already pinned to this run and standing in `SCHEDULED` becomes
        due, its `due_at` set to the current logical clock plus that client's
        `delivery_sla_hours`, walked in client `created_at` ascending order".

        Design: Difficulty/boundary_precision_check/billing_volume_bracket_at_exactly_150000_gross
        """
        base = _dma_512_published_run_with_two_scheduled_rows(panel)

        assert panel.read_client(base["subscriber"]["id"])["delivery_sla_hours"] == 72
        assert (
            panel.read_deliverable(base["row_17"]["id"])["due_at"]
            == "2026-08-15T00:00:00.000Z"
        )
        assert (
            panel.read_deliverable(base["row_16"]["id"])["due_at"]
            == "2026-08-15T00:00:00.000Z"
        )


def _dma_513_scan_over_two_meters(panel: PanelHarness):
    """DMA-513: one meter with no coverage at all, one with a single credited minute."""
    base = _measurement_base(
        panel,
        name="Metro Nu",
        market_code="DMA-513",
        dma_rank=13,
        cell_specs=[
            {
                "age_band": "P18_34",
                "income_band": "MID",
                "geo_zone": "URBAN",
                "target_households": 2,
                "base_incentive_cents": 2000,
            }
        ],
        populations=[(200000, 500000)],
        fault_missing_minutes_threshold=1440,
    )
    cell = base["cells"][0]
    home_a = panel.active_household(base["market"]["id"], cell["id"], persons_count=2)
    home_b = panel.active_household(base["market"]["id"], cell["id"], persons_count=3)

    filled = panel.read_quota_cell(cell["id"])
    assert filled["intab_count"] == 2
    assert filled["quota_status"] == "FILLED"
    assert filled["incentive_boost_active"] is False
    before = panel.read_market(base["market"]["id"])
    assert before["incentive_budget_reserved_cents"] == 0
    assert before["recruitment_posture"] == "CLOSED"

    panel.set_clock("2026-08-11T00:00:00Z")
    panel.ingest_interval(
        home_b["tuner"]["id"],
        home_b["household"]["id"],
        "2026-08-10T12:00:00Z",
        "2026-08-10T12:01:00Z",
        1,
        station_code="WXYZ",
    )
    run = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso=WINDOW_0810_START,
        window_end_iso=WINDOW_0810_END,
    )
    base["cell"] = cell
    base["home_a"] = home_a
    base["home_b"] = home_b
    base["run"] = run
    return base


class TestMeterFaultThresholdAtExactly1440:
    """`fault_missing_minutes_threshold` is inclusive at the bottom: 1440 faults, 1439 does not."""

    def test_shortfall_exactly_at_the_threshold_faults_the_meter(
        self, panel: PanelHarness
    ):
        """A meter with zero coverage misses exactly 1440 minutes and is FAULTED.

        PRD 3.3: "Missing minutes at or above `fault_missing_minutes_threshold`
        drive `health_status` to `FAULTED` with `last_fault_code` set to
        `MISSING_INTERVALS` and `fault_count` raised by one; a meter missing exactly
        the threshold is faulted, and one minute less is `SUSPECT`."

        Design: Difficulty/boundary_precision_check/meter_fault_threshold_at_exactly_1440_versus_1439
        """
        base = _dma_513_scan_over_two_meters(panel)

        scanned = validate_success(
            panel.client.detect_faults(panel.statistician, base["run"]["id"]), 200
        )
        assert scanned["window_minutes"] == 1440
        assert scanned["state"] == "OPEN"

        meter_a = panel.read_meter(base["home_a"]["tuner"]["id"])
        assert meter_a["missing_minutes_last_scan"] == 1440
        assert meter_a["health_status"] == "FAULTED"
        assert meter_a["last_fault_code"] == "MISSING_INTERVALS"
        assert meter_a["fault_count"] == 1
        assert meter_a["install_status"] == "INSTALLED"
        assert panel.read_household(base["home_a"]["household"]["id"])["status"] == "FAULT_HOLD"

    def test_shortfall_one_minute_below_the_threshold_is_only_suspect(
        self, panel: PanelHarness
    ):
        """A single credited minute leaves 1439 missing: SUSPECT, and no cascade at all.

        PRD 3.3: "Missing minutes at or above the suspect floor but below the
        threshold drive `health_status` to `SUSPECT`".

        Design: Difficulty/boundary_precision_check/meter_fault_threshold_at_exactly_1440_versus_1439
        """
        base = _dma_513_scan_over_two_meters(panel)

        validate_success(
            panel.client.detect_faults(panel.statistician, base["run"]["id"]), 200
        )

        meter_b = panel.read_meter(base["home_b"]["tuner"]["id"])
        assert meter_b["missing_minutes_last_scan"] == 1439
        assert meter_b["health_status"] == "SUSPECT"
        assert meter_b["last_fault_code"] is None
        assert meter_b["fault_count"] == 0
        assert meter_b["install_status"] == "INSTALLED"
        assert panel.read_household(base["home_b"]["household"]["id"])["status"] == "ACTIVE"

    def test_only_the_faulted_meter_drives_the_cell_and_market_cascade(
        self, panel: PanelHarness
    ):
        """One FAULTED meter re-arms the boost and reopens the market; SUSPECT does nothing.

        PRD 3.3: "every meter it drives to `FAULTED` fires cascade links 2 through 5
        exactly as a hand-filed fault report would."

        Design: Difficulty/boundary_precision_check/meter_fault_threshold_at_exactly_1440_versus_1439
        """
        base = _dma_513_scan_over_two_meters(panel)

        validate_success(
            panel.client.detect_faults(panel.statistician, base["run"]["id"]), 200
        )

        cell = panel.read_quota_cell(base["cell"]["id"])
        assert cell["intab_count"] == 1
        assert cell["fill_rate"] == 0.5000
        assert cell["quota_status"] == "UNDER_TARGET"
        assert cell["incentive_boost_active"] is True
        assert cell["effective_incentive_multiplier"] == 1.25

        market = panel.read_market(base["market"]["id"])
        assert market["incentive_budget_reserved_cents"] == 1000
        assert market["recruitment_posture"] == "OPEN"
        assert market["posture_changed_at"] == "2026-08-11T00:00:00.000Z"

    def test_the_scan_refreshes_both_rolling_compliance_rates(
        self, panel: PanelHarness
    ):
        """A silent home and a home under the 30-minute floor both land on 0.0000.

        PRD 3.3: "Every scanned meter's `missing_minutes_last_scan` is updated
        regardless of the verdict, and `compliance_rate_rolling_30` is refreshed for
        every scanned household."

        Design: Difficulty/boundary_precision_check/meter_fault_threshold_at_exactly_1440_versus_1439
        """
        base = _dma_513_scan_over_two_meters(panel)

        validate_success(
            panel.client.detect_faults(panel.statistician, base["run"]["id"]), 200
        )

        assert (
            panel.read_household(base["home_a"]["household"]["id"])[
                "compliance_rate_rolling_30"
            ]
            == 0.0000
        )
        assert (
            panel.read_household(base["home_b"]["household"]["id"])[
                "compliance_rate_rolling_30"
            ]
            == 0.0000
        )


def _dma_514_two_edited_runs(panel: PanelHarness):
    """DMA-514: two touching windows over one market, both EDITED and ready to weight.

    The 08-09 window holds h1 and h2 only, so cell Q's FINAL denominator is 1; the
    08-10 window holds h3 as well, so the same denominator is 2 and every base weight
    of that cell halves.  h1's own base weight is 270000.0000 in both runs.
    """
    base = _measurement_base(
        panel,
        name="Metro Xi",
        market_code="DMA-514",
        dma_rank=14,
        cell_specs=[
            {
                "age_band": "P18_34",
                "income_band": "HIGH",
                "geo_zone": "URBAN",
                "target_households": 1,
                "base_incentive_cents": 2000,
            },
            {
                "age_band": "P35_54",
                "income_band": "MID",
                "geo_zone": "SUBURBAN",
                "target_households": 2,
                "base_incentive_cents": 2000,
            },
        ],
        populations=[(270000, 600000), (180000, 400000)],
        outlier_weight_ratio_cap=1.2,
    )
    cell_p, cell_q = base["cells"]
    home_1 = panel.active_household(base["market"]["id"], cell_p["id"], persons_count=2)
    home_2 = panel.active_household(base["market"]["id"], cell_q["id"], persons_count=3)
    home_3 = panel.active_household(
        base["market"]["id"],
        cell_q["id"],
        persons_count=1,
        recruitment_source="RDD_PHONE",
    )

    panel.set_clock("2026-08-11T00:00:00Z")
    panel.ingest_interval(
        home_1["tuner"]["id"],
        home_1["household"]["id"],
        "2026-08-09T18:00:00Z",
        "2026-08-09T23:50:00Z",
        350,
        station_code="WXYZ",
    )
    panel.ingest_interval(
        home_1["tuner"]["id"],
        home_1["household"]["id"],
        "2026-08-10T18:00:00Z",
        "2026-08-10T23:50:00Z",
        350,
        station_code="WXYZ",
    )
    panel.ingest_interval(
        home_2["tuner"]["id"],
        home_2["household"]["id"],
        "2026-08-09T06:00:00Z",
        "2026-08-09T18:10:00Z",
        730,
        station_code="WXYZ",
    )
    panel.ingest_interval(
        home_2["tuner"]["id"],
        home_2["household"]["id"],
        "2026-08-10T06:00:00Z",
        "2026-08-10T18:10:00Z",
        730,
        station_code="WXYZ",
    )
    panel.ingest_interval(
        home_3["tuner"]["id"],
        home_3["household"]["id"],
        "2026-08-10T20:00:00Z",
        "2026-08-10T21:00:00Z",
        60,
        station_code="WXYZ",
    )

    run_0809 = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso="2026-08-09T00:00:00Z",
        window_end_iso="2026-08-10T00:00:00Z",
    )
    run_0810 = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso=WINDOW_0810_START,
        window_end_iso=WINDOW_0810_END,
    )
    run_0809 = panel.edit_run(run_0809["id"])
    run_0810 = panel.edit_run(run_0810["id"])
    assert run_0809["contributing_household_count"] == 2
    assert run_0810["contributing_household_count"] == 3

    base["cell_p"] = cell_p
    base["cell_q"] = cell_q
    base["home_1"] = home_1
    base["home_2"] = home_2
    base["home_3"] = home_3
    base["run_0809"] = run_0809
    base["run_0810"] = run_0810
    return base


class TestWeightCapAtExactlyCapIsNotCapped:
    """The run-relative weight cap is a strict `>` comparison, never `>=`."""

    def test_base_weight_exactly_at_the_cap_is_left_uncapped(
        self, panel: PanelHarness
    ):
        """270000.0000 against a cap of exactly 270000.0000 keeps its full weight.

        PRD 3.7: "Rows whose `base_weight` is **strictly greater** than the cap are
        the capped rows; a row exactly at the cap is not capped."

        Design: Difficulty/boundary_precision_check/weight_cap_at_exactly_cap_is_not_capped
        """
        base = _dma_514_two_edited_runs(panel)

        weighted = panel.weight_run(base["run_0809"]["id"], weight_variant="FINAL")
        assert _weight_row_count(panel, weighted["id"]) == 2

        row_1 = _weights_of(panel, weighted["id"], base["home_1"]["household"]["id"])
        row_2 = _weights_of(panel, weighted["id"], base["home_2"]["household"]["id"])
        # mass 450000.0000 over 2 rows means 225000.0000, times 1.2 is 270000.0000.
        assert row_1["base_weight"] == 270000.0000
        assert row_2["base_weight"] == 180000.0000
        assert row_1["capped"] is False
        assert row_1["adjusted_weight"] == 270000.0000
        assert row_2["capped"] is False
        assert row_2["adjusted_weight"] == 180000.0000
        assert weighted["total_weight_mass"] == 450000.0000
        assert "WEIGHT_CAP_APPLIED" not in weighted["limitation_disclosures"]

    def test_base_weight_above_the_cap_is_capped_and_redistributed(
        self, panel: PanelHarness
    ):
        """The identical 270000.0000 base is trimmed to 180000.0000 once the cap moves.

        PRD 3.7: "Every capped row has its `adjusted_weight` set to the cap and its
        `capped` flag set to true."

        Design: Difficulty/boundary_precision_check/weight_cap_at_exactly_cap_is_not_capped
        """
        base = _dma_514_two_edited_runs(panel)

        weighted = panel.weight_run(base["run_0810"]["id"], weight_variant="FINAL")
        assert _weight_row_count(panel, weighted["id"]) == 3

        row_1 = _weights_of(panel, weighted["id"], base["home_1"]["household"]["id"])
        row_2 = _weights_of(panel, weighted["id"], base["home_2"]["household"]["id"])
        row_3 = _weights_of(panel, weighted["id"], base["home_3"]["household"]["id"])
        # Cell Q's FINAL denominator is 2 here, so 180000 / 2 is 90000.0000 apiece;
        # mass 450000.0000 over 3 rows is 150000.0000, times 1.2 is 180000.0000.
        assert row_1["base_weight"] == 270000.0000
        assert row_2["base_weight"] == 90000.0000
        assert row_3["base_weight"] == 90000.0000
        assert row_1["capped"] is True
        assert row_1["adjusted_weight"] == 180000.0000
        # The 90000.0000 excess is shared in proportion to base weight: 45000.0000 each.
        assert row_2["capped"] is False
        assert row_2["adjusted_weight"] == 135000.0000
        assert row_3["capped"] is False
        assert row_3["adjusted_weight"] == 135000.0000
        assert weighted["total_weight_mass"] == 450000.0000
        assert "WEIGHT_CAP_APPLIED" in weighted["limitation_disclosures"]

    def test_only_the_cap_moved_between_the_two_runs(self, panel: PanelHarness):
        """One household, one base weight, two verdicts: the cap is run-relative.

        PRD 3.7: "The cap is relative to this run's own mean and never to any global
        constant, so the same household can be capped in one run and untouched in
        another."

        Design: Difficulty/boundary_precision_check/weight_cap_at_exactly_cap_is_not_capped
        """
        base = _dma_514_two_edited_runs(panel)
        household_1 = base["home_1"]["household"]["id"]

        uncapped_run = panel.weight_run(base["run_0809"]["id"], weight_variant="FINAL")
        capped_run = panel.weight_run(base["run_0810"]["id"], weight_variant="FINAL")

        uncapped = _weights_of(panel, uncapped_run["id"], household_1)
        capped = _weights_of(panel, capped_run["id"], household_1)
        assert uncapped["base_weight"] == capped["base_weight"] == 270000.0000
        assert uncapped["capped"] is False
        assert capped["capped"] is True
        # Redistribution conserves the mass, so both runs report the same total.
        assert uncapped_run["total_weight_mass"] == 450000.0000
        assert capped_run["total_weight_mass"] == 450000.0000

    def test_the_projection_sums_already_rounded_contributions(
        self, panel: PanelHarness
    ):
        """156875 for the uncapped run and 117813 for the capped one.

        PRD 3.7: "each household's `contribution` is its `adjusted_weight` multiplied
        by its summed usable minutes and divided by the run's `window_minutes`,
        rounded half up to 2 decimal places."

        Design: Difficulty/boundary_precision_check/weight_cap_at_exactly_cap_is_not_capped
        """
        base = _dma_514_two_edited_runs(panel)

        run_a = panel.weight_run(base["run_0809"]["id"], weight_variant="FINAL")
        assert run_a["window_minutes"] == 1440
        assert (
            _weights_of(panel, run_a["id"], base["home_1"]["household"]["id"])[
                "contribution"
            ]
            == 65625.00
        )
        assert (
            _weights_of(panel, run_a["id"], base["home_2"]["household"]["id"])[
                "contribution"
            ]
            == 91250.00
        )
        assert run_a["projected_average_audience"] == 156875

        run_b = panel.weight_run(base["run_0810"]["id"], weight_variant="FINAL")
        assert (
            _weights_of(panel, run_b["id"], base["home_1"]["household"]["id"])[
                "contribution"
            ]
            == 43750.00
        )
        assert (
            _weights_of(panel, run_b["id"], base["home_2"]["household"]["id"])[
                "contribution"
            ]
            == 68437.50
        )
        assert (
            _weights_of(panel, run_b["id"], base["home_3"]["household"]["id"])[
                "contribution"
            ]
            == 5625.00
        )
        # 43750.00 + 68437.50 + 5625.00 is 117812.50, and half up takes it to 117813.
        assert run_b["projected_average_audience"] == 117813
