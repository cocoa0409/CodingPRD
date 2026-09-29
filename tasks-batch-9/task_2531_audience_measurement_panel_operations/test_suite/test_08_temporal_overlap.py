"""Temporal overlap over a contended resource: one meter, and one market's run windows.

Both scenarios treat their periods as half-open, so a touching endpoint is never a
collision, and both filter the blocking set by state - an `INVALIDATED` block and a
`SUPERSEDED` run stop blocking, while an `EDITED` block and a `PUBLISHED` run do not.
"""

from prd_bench_local_runner.testing import (
    validate_error,
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


ONE_CELL = [
    {
        "age_band": "P18_34",
        "income_band": "MID",
        "geo_zone": "URBAN",
        "target_households": 1,
        "base_incentive_cents": 2000,
    }
]


def _interval_count(panel: PanelHarness, meter_id: str, **filters) -> int:
    """How many blocks of one device match the filters."""
    _rows, meta = validate_paginated(
        panel.client.list_tuning_intervals(
            panel.statistician, meter_id=meter_id, limit=100, **filters
        )
    )
    return meta["total_count"]


def _ingest(panel: PanelHarness, meter_id: str, household_id: str, start_iso, end_iso,
            minutes: int, station_code: str = "WXYZ"):
    """The raw POST /tuning-intervals response, for the calls whose code matters."""
    return panel.client.create_tuning_interval(
        panel.statistician,
        meter_id=meter_id,
        household_id=household_id,
        source_methodology="INHOME_TUNER",
        start_iso=start_iso,
        end_iso=end_iso,
        station_code=station_code,
        tuning_minutes=minutes,
    )


def _dma_517_two_touching_blocks(panel: PanelHarness):
    """DMA-517: one meter carrying [18:00, 23:50) and the touching [23:50, 23:59)."""
    base = _measurement_base(
        panel,
        name="Metro Rho",
        market_code="DMA-517",
        dma_rank=17,
        cell_specs=ONE_CELL,
        populations=[(120000, 300000)],
        invalid_tuning_max_minutes=300,
    )
    built = panel.active_household(
        base["market"]["id"], base["cells"][0]["id"], persons_count=2
    )
    panel.set_clock("2026-08-11T00:00:00Z")
    meter_id = built["tuner"]["id"]
    household_id = built["household"]["id"]

    first = validate_success(
        _ingest(panel, meter_id, household_id, "2026-08-10T18:00:00Z",
                "2026-08-10T23:50:00Z", 350),
        201,
    )
    second = validate_success(
        _ingest(panel, meter_id, household_id, "2026-08-10T23:50:00Z",
                "2026-08-10T23:59:00Z", 9),
        201,
    )
    base["built"] = built
    base["meter_id"] = meter_id
    base["household_id"] = household_id
    base["t1"] = first
    base["t2"] = second
    return base


def _dma_517_edited_run(panel: PanelHarness):
    """The same meter after the edit pass has invalidated the over-long block."""
    base = _dma_517_two_touching_blocks(panel)
    run = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso=WINDOW_0810_START,
        window_end_iso=WINDOW_0810_END,
    )
    base["run"] = panel.edit_run(run["id"])
    return base


class TestTuningIntervalHalfOpenOverlapOnOneMeter:
    """The blocking set is `[start_iso, end_iso)` on one meter, filtered by state."""

    def test_touching_endpoints_are_not_an_overlap(self, panel: PanelHarness):
        """A block starting exactly where the previous one ended is accepted.

        PRD 3.6: "The new block, treated as half-open - `start_iso` inclusive,
        `end_iso` exclusive - must not overlap any existing interval of the **same
        meter** whose `state` is `RAW`, `EDITED` or `ASCRIBED`, otherwise
        `ERR_INTERVAL_OVERLAP`. Touching endpoints do not overlap".

        Design: Difficulty/resource_temporal_overlap/tuning_interval_half_open_overlap_on_one_meter
        """
        base = _dma_517_two_touching_blocks(panel)

        assert base["t1"]["state"] == "RAW"
        assert base["t1"]["usable_minutes"] == 0
        assert base["t1"]["ascribed"] is False
        assert base["t1"]["processing_run_id"] is None
        assert base["t2"]["state"] == "RAW"
        assert base["t2"]["start_iso"] == base["t1"]["end_iso"]
        assert _interval_count(panel, base["meter_id"]) == 2

    def test_a_block_inside_a_raw_record_is_refused(self, panel: PanelHarness):
        """[19:00, 20:00) sits wholly inside the RAW [18:00, 23:50) and is rejected.

        PRD 3.6: "must not overlap any existing interval of the **same meter** whose
        `state` is `RAW`, `EDITED` or `ASCRIBED`, otherwise `ERR_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tuning_interval_half_open_overlap_on_one_meter
        """
        base = _dma_517_two_touching_blocks(panel)

        response = _ingest(
            panel,
            base["meter_id"],
            base["household_id"],
            "2026-08-10T19:00:00Z",
            "2026-08-10T20:00:00Z",
            60,
            station_code="WPQR",
        )
        validate_error(response, "ERR_INTERVAL_OVERLAP")
        assert _interval_count(panel, base["meter_id"]) == 2

    def test_the_edit_pass_invalidates_the_over_long_block_and_credits_the_short_one(
        self, panel: PanelHarness
    ):
        """350 minutes breaks the 300-minute ceiling; the 9-minute block is credited.

        PRD 3.6: "A claimed record whose `tuning_minutes` exceeds the rule set's
        `invalid_tuning_max_minutes` moves to `state` `INVALIDATED` with
        `invalidation_reason` `OVER_MAX_TUNING` and `usable_minutes` 0."

        Design: Difficulty/resource_temporal_overlap/tuning_interval_half_open_overlap_on_one_meter
        """
        base = _dma_517_edited_run(panel)

        assert base["run"]["invalidated_interval_count"] == 1
        assert base["run"]["contributing_household_count"] == 1
        assert base["run"]["ascribed_interval_count"] == 0

        first = panel.read_interval(base["t1"]["id"])
        assert first["state"] == "INVALIDATED"
        assert first["invalidation_reason"] == "OVER_MAX_TUNING"
        assert first["usable_minutes"] == 0
        second = panel.read_interval(base["t2"]["id"])
        assert second["state"] == "EDITED"
        assert second["usable_minutes"] == 9
        # One surviving record leaves no adjacent pair, so nothing was ascribed.
        assert _interval_count(panel, base["meter_id"], ascribed=True) == 0

    def test_an_invalidated_record_no_longer_blocks_re_ingest(
        self, panel: PanelHarness
    ):
        """The byte-identical request refused earlier is now accepted.

        PRD 3.6: "An `INVALIDATED` record does not block re-ingest".

        Design: Difficulty/resource_temporal_overlap/tuning_interval_half_open_overlap_on_one_meter
        """
        base = _dma_517_edited_run(panel)

        reingested = validate_success(
            _ingest(
                panel,
                base["meter_id"],
                base["household_id"],
                "2026-08-10T19:00:00Z",
                "2026-08-10T20:00:00Z",
                60,
                station_code="WPQR",
            ),
            201,
        )
        assert reingested["state"] == "RAW"
        assert reingested["usable_minutes"] == 0
        assert reingested["processing_run_id"] is None
        assert _interval_count(panel, base["meter_id"]) == 3

    def test_an_edited_record_still_blocks(self, panel: PanelHarness):
        """[23:45, 23:55) straddles the EDITED [23:50, 23:59) and is refused.

        PRD 3.6: "must not overlap any existing interval of the **same meter** whose
        `state` is `RAW`, `EDITED` or `ASCRIBED`, otherwise `ERR_INTERVAL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/tuning_interval_half_open_overlap_on_one_meter
        """
        base = _dma_517_edited_run(panel)
        validate_success(
            _ingest(
                panel,
                base["meter_id"],
                base["household_id"],
                "2026-08-10T19:00:00Z",
                "2026-08-10T20:00:00Z",
                60,
                station_code="WPQR",
            ),
            201,
        )

        response = _ingest(
            panel,
            base["meter_id"],
            base["household_id"],
            "2026-08-10T23:45:00Z",
            "2026-08-10T23:55:00Z",
            10,
            station_code="WPQR",
        )
        validate_error(response, "ERR_INTERVAL_OVERLAP")
        # One INVALIDATED, one EDITED and one RAW row survive the whole sequence.
        assert _interval_count(panel, base["meter_id"]) == 3

    def test_the_rolling_rate_reads_the_surviving_reported_minutes(
        self, panel: PanelHarness
    ):
        """9 credited plus 60 raw minutes on one reported day is a perfect rate.

        PRD 3.6: "The rate is the compliant days divided by the evaluated days,
        rounded half up to 4 decimal places".

        Design: Difficulty/resource_temporal_overlap/tuning_interval_half_open_overlap_on_one_meter
        """
        base = _dma_517_edited_run(panel)

        validate_success(
            _ingest(
                panel,
                base["meter_id"],
                base["household_id"],
                "2026-08-10T19:00:00Z",
                "2026-08-10T20:00:00Z",
                60,
                station_code="WPQR",
            ),
            201,
        )
        household = panel.read_household(base["household_id"])
        assert household["compliance_rate_rolling_30"] == 1.0000


def _run_count(panel: PanelHarness, market_id: str) -> int:
    """How many processing runs the market carries, whatever their state."""
    _rows, meta = validate_paginated(
        panel.client.list_processing_runs(
            panel.statistician, market_id=market_id, limit=100
        )
    )
    return meta["total_count"]


def _open_run_raw(panel: PanelHarness, base, start_iso: str, end_iso: str, version=None):
    """The raw POST /processing-runs response, with an explicit OCC token."""
    if version is None:
        version = panel.market_version(base["market"]["id"])
    return panel.client.create_processing_run(
        panel.statistician,
        market_id=base["market"]["id"],
        universe_estimate_id=base["universe"]["id"],
        edit_rule_set_id=base["rule_set"]["id"],
        window_start_iso=start_iso,
        window_end_iso=end_iso,
        expected_market_version=version,
    )


def _dma_518_edited_run(panel: PanelHarness):
    """DMA-518: run r1 over [08-10, 08-11) EDITED, having claimed the only block."""
    base = _measurement_base(
        panel,
        name="Metro Sigma",
        market_code="DMA-518",
        dma_rank=18,
        cell_specs=ONE_CELL,
        populations=[(120000, 300000)],
    )
    built = panel.active_household(
        base["market"]["id"], base["cells"][0]["id"], persons_count=2
    )
    panel.set_clock("2026-08-11T00:00:00Z")
    interval = panel.ingest_interval(
        built["tuner"]["id"],
        built["household"]["id"],
        "2026-08-10T18:00:00Z",
        "2026-08-10T23:50:00Z",
        350,
        station_code="WXYZ",
    )
    run_1 = panel.open_run(
        base["market"]["id"],
        base["universe"]["id"],
        base["rule_set"]["id"],
        window_start_iso=WINDOW_0810_START,
        window_end_iso=WINDOW_0810_END,
    )
    run_1 = panel.edit_run(run_1["id"])
    assert run_1["contributing_household_count"] == 1
    assert panel.read_interval(interval["id"])["processing_run_id"] == run_1["id"]

    # Every window used below must be wholly in the past.
    panel.set_clock("2026-08-12T00:00:00Z")
    base["built"] = built
    base["interval"] = interval
    base["run_1"] = run_1
    return base


def _dma_518_with_touching_neighbour(panel: PanelHarness):
    """r1 EDITED plus r3 opened over the touching window [08-11, 08-12)."""
    base = _dma_518_edited_run(panel)
    run_3 = validate_success(
        _open_run_raw(panel, base, WINDOW_0810_END, "2026-08-12T00:00:00Z"), 201
    )
    assert run_3["state"] == "OPEN"
    base["run_3"] = run_3
    return base


class TestRunWindowIdenticalSupersedesPartialOverlapRejected:
    """A partial overlap is fatal, a touching window is fine, an identical one supersedes."""

    def test_a_partially_overlapping_window_is_refused(self, panel: PanelHarness):
        """[08-10T12:00, 08-11T12:00) half-covers r1's window and is rejected.

        PRD 3.6: "The run window must not **partially** overlap the window of any
        other processing run of the same market whose `state` is not `SUPERSEDED`,
        otherwise `ERR_RUN_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/run_window_identical_supersedes_partial_overlap_rejected
        """
        base = _dma_518_edited_run(panel)

        response = _open_run_raw(
            panel, base, "2026-08-10T12:00:00Z", "2026-08-11T12:00:00Z"
        )
        validate_error(response, "ERR_RUN_WINDOW_OVERLAP")

        assert panel.read_run(base["run_1"]["id"])["state"] == "EDITED"
        assert _run_count(panel, base["market"]["id"]) == 1

    def test_the_refused_creation_leaves_the_occ_token_valid(
        self, panel: PanelHarness
    ):
        """A rejected write is not a mutation, so the market's `version` does not move.

        PRD 2.5: "`version` - an integer that starts at 1 on creation and increments by
        exactly 1 on every mutation of the row."

        Design: Difficulty/resource_temporal_overlap/run_window_identical_supersedes_partial_overlap_rejected
        """
        base = _dma_518_edited_run(panel)
        before = panel.market_version(base["market"]["id"])

        validate_error(
            _open_run_raw(
                panel, base, "2026-08-10T12:00:00Z", "2026-08-11T12:00:00Z", before
            ),
            "ERR_RUN_WINDOW_OVERLAP",
        )
        assert panel.market_version(base["market"]["id"]) == before

        # The same token the refused call carried is still current, so it is accepted.
        accepted = validate_success(
            _open_run_raw(
                panel, base, WINDOW_0810_END, "2026-08-12T00:00:00Z", before
            ),
            201,
        )
        assert accepted["state"] == "OPEN"
        assert accepted["window_minutes"] == 1440

    def test_a_touching_window_is_accepted(self, panel: PanelHarness):
        """A run starting exactly at r1's `window_end_iso` does not overlap it.

        PRD 3.6: "The comparison is half-open, so a run starting exactly at another
        run's `window_end_iso` is accepted."

        Design: Difficulty/resource_temporal_overlap/run_window_identical_supersedes_partial_overlap_rejected
        """
        base = _dma_518_with_touching_neighbour(panel)

        assert base["run_3"]["window_start_iso"] == base["run_1"]["window_end_iso"]
        assert base["run_3"]["state"] == "OPEN"
        assert base["run_3"]["superseded_by_run_id"] is None
        assert panel.read_run(base["run_1"]["id"])["state"] == "EDITED"
        assert _run_count(panel, base["market"]["id"]) == 2

    def test_a_byte_identical_window_supersedes_the_older_run(
        self, panel: PanelHarness
    ):
        """The single exception to the overlap rule displaces the EDITED run.

        PRD 3.6: "A byte-identical window is the single exception to the overlap rule:
        it is accepted and supersedes the older run - unless that older run is
        `PUBLISHED`".

        Design: Difficulty/resource_temporal_overlap/run_window_identical_supersedes_partial_overlap_rejected
        """
        base = _dma_518_with_touching_neighbour(panel)

        run_4 = validate_success(
            _open_run_raw(panel, base, WINDOW_0810_START, WINDOW_0810_END), 201
        )
        assert run_4["state"] == "OPEN"

        superseded = panel.read_run(base["run_1"]["id"])
        assert superseded["state"] == "SUPERSEDED"
        assert superseded["superseded_by_run_id"] == run_4["id"]
        assert superseded["limitation_disclosures"] == []
        # The touching neighbour shares no endpoint pair with the new run.
        assert panel.read_run(base["run_3"]["id"])["state"] == "OPEN"
        assert _run_count(panel, base["market"]["id"]) == 3

    def test_the_supersession_releases_the_older_runs_claim(
        self, panel: PanelHarness
    ):
        """The block returns to the pool and the new run re-claims and projects it.

        PRD 3.6: "every tuning interval it had claimed returns to `state` `RAW` with
        `processing_run_id` null, `usable_minutes` 0 and `invalidation_reason` null".

        Design: Difficulty/resource_temporal_overlap/run_window_identical_supersedes_partial_overlap_rejected
        """
        base = _dma_518_with_touching_neighbour(panel)

        run_4 = validate_success(
            _open_run_raw(panel, base, WINDOW_0810_START, WINDOW_0810_END), 201
        )
        released = panel.read_interval(base["interval"]["id"])
        assert released["state"] == "RAW"
        assert released["usable_minutes"] == 0
        assert released["processing_run_id"] is None
        assert released["invalidation_reason"] is None

        edited = panel.edit_run(run_4["id"])
        assert edited["contributing_household_count"] == 1
        weighted = panel.weight_run(run_4["id"], weight_variant="FINAL")
        assert weighted["total_weight_mass"] == 120000.0000
        assert weighted["projected_average_audience"] == 29167

    def test_an_identical_window_against_a_published_run_is_refused(
        self, panel: PanelHarness
    ):
        """Published output is never quietly displaced, identical window or not.

        PRD 3.6: "A `PUBLISHED` run is never superseded this way, because a published
        run still counts as non-superseded for the overlap check and an
        identical-window re-run against it is rejected outright."

        Design: Difficulty/resource_temporal_overlap/run_window_identical_supersedes_partial_overlap_rejected
        """
        base = _dma_518_with_touching_neighbour(panel)
        run_4 = validate_success(
            _open_run_raw(panel, base, WINDOW_0810_START, WINDOW_0810_END), 201
        )
        panel.edit_run(run_4["id"])
        panel.weight_run(run_4["id"], weight_variant="FINAL")
        published = panel.publish_run(run_4["id"])
        assert published["state"] == "PUBLISHED"

        response = _open_run_raw(panel, base, WINDOW_0810_START, WINDOW_0810_END)
        validate_error(response, "ERR_RUN_WINDOW_OVERLAP")
        assert panel.read_run(run_4["id"])["state"] == "PUBLISHED"
        # r1 superseded, r3 open and r4 published: no fourth row was ever created.
        assert _run_count(panel, base["market"]["id"]) == 3
