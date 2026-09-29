"""Endpoint surface: the declared collection filters, their pagination envelope
and the read projections behind them.

Each listing test drives one of the PRD 2.3 filter sets against a fixture built
so that the filter has to discriminate (a boolean that is true for some rows and
false for others, a status that is not constant across the table), and asserts
the ordering the contract declares together with `total_count`, `has_more`,
`limit` and `offset`. The single-resource reads pin the projection the listing
pages over.
"""

from datetime import datetime, timedelta

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import MISSING_UUID
from test_helpers.assertions import (
    assert_ordered_by,
    expected_contribution,
    ids_of,
)
from test_helpers.constants import PREMIUM_SLA_HOURS
from test_helpers.fixtures import (
    CLOCK_T0,
    CLOCK_T1,
    WINDOW_MINUTES,
    WINDOW_START,
    PanelHarness,
)
from test_helpers.test_users import make_auditor_headers


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


CLOCK_AUG_05 = "2026-08-05T00:00:00Z"
CLOCK_AUG_04_LAST_SECOND = "2026-08-04T23:59:59Z"
CLOCK_SEP_01 = "2026-09-01T00:00:00Z"


# ======================================================================
# GET /quota-cells and GET /quota-cells/{quota_cell_id}
# ======================================================================

def _listing_markets(panel: PanelHarness) -> dict:
    """Two markets: one with three cells of which exactly one is FILLED.

    Every cell is created before the household is recruited, so the parent
    market is still `OPEN` at intake. Cell A has `target_households` 1 and one
    `ACTIVE` home, so its fill rate is 1 / 1 == 1.0000; cells B and C are left
    empty and stay `UNDER_TARGET` with their boosts armed.
    """
    market = panel.create_market(
        name="Metro Listing", dma_rank=181, incentive_budget_cents=500000
    )
    cell_a = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=1,
        base_incentive_cents=1000,
    )
    cell_b = panel.create_quota_cell(
        market["id"],
        age_band="P35_54",
        income_band="HIGH",
        geo_zone="SUBURBAN",
        target_households=4,
        base_incentive_cents=1000,
    )
    cell_c = panel.create_quota_cell(
        market["id"],
        age_band="P55_PLUS",
        income_band="LOW",
        geo_zone="RURAL",
        target_households=4,
        base_incentive_cents=1000,
    )
    other_market = panel.create_market(
        name="Metro Elsewhere", dma_rank=182, incentive_budget_cents=500000
    )
    other_cell = panel.create_quota_cell(
        other_market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=4,
        base_incentive_cents=1000,
    )
    panel.active_household(market["id"], cell_a["id"], persons_count=2)
    return {
        "market": market,
        "cell_a": cell_a,
        "cell_b": cell_b,
        "cell_c": cell_c,
        "other_market": other_market,
        "other_cell": other_cell,
    }


class TestQuotaCellListing:
    """`market_id`, `quota_status` and `incentive_boost_active` on GET /quota-cells."""

    def test_market_filter_scopes_the_page_to_one_market(self, panel: PanelHarness):
        """The `market_id` filter returns that market's three cells in creation order.

        PRD 2.3: "Quota cells: `market_id`, `quota_status`, `incentive_boost_active`".

        PRD 2.3: "Unless a collection states otherwise below, list results are
        ordered by `created_at` ascending."

        PRD 2.3: "Both are reflected back in the envelope's `meta` object, alongside
        `total_count` (the number of rows the filter matched before pagination) and
        `has_more` (true when rows remain beyond this page)."

        Design: Corner/endpoints/quota_cell_listing_filters_by_market_status_and_boost_flag
        """
        built = _listing_markets(panel)

        rows, meta = validate_paginated(
            panel.client.list_quota_cells(panel.ops, market_id=built["market"]["id"])
        )

        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(rows) == 3
        assert {row["market_id"] for row in rows} == {built["market"]["id"]}
        assert set(ids_of(rows)) == {
            built["cell_a"]["id"],
            built["cell_b"]["id"],
            built["cell_c"]["id"],
        }
        assert_ordered_by(rows, [("created_at", "asc")])

    def test_status_filter_returns_only_the_under_target_cells(self, panel: PanelHarness):
        """`quota_status` UNDER_TARGET matches the two empty cells and not the filled one.

        PRD 2.3: "Quota cells: `market_id`, `quota_status`, `incentive_boost_active`".

        PRD 3.1: "The status follows from the rate: `FILLED` when the rate is 1.0000
        or more, `ON_TARGET` when the rate is 0.8000 or more but below 1.0000, and
        `UNDER_TARGET` in every other case."

        Design: Corner/endpoints/quota_cell_listing_filters_by_market_status_and_boost_flag
        """
        built = _listing_markets(panel)

        rows, meta = validate_paginated(
            panel.client.list_quota_cells(
                panel.ops, market_id=built["market"]["id"], quota_status="UNDER_TARGET"
            )
        )

        assert meta["total_count"] == 2
        assert set(ids_of(rows)) == {built["cell_b"]["id"], built["cell_c"]["id"]}
        assert {row["quota_status"] for row in rows} == {"UNDER_TARGET"}

    def test_boost_filter_agrees_with_the_status_filter(self, panel: PanelHarness):
        """`incentive_boost_active` true selects exactly the two UNDER_TARGET cells.

        PRD 2.3: "Quota cells: `market_id`, `quota_status`, `incentive_boost_active`".

        PRD 3.1: "When the graded status is `UNDER_TARGET` and the cell's boost is
        not already armed, `incentive_boost_active` becomes true,
        `effective_incentive_multiplier` becomes 1.25".

        Design: Corner/endpoints/quota_cell_listing_filters_by_market_status_and_boost_flag
        """
        built = _listing_markets(panel)

        rows, meta = validate_paginated(
            panel.client.list_quota_cells(
                panel.ops, market_id=built["market"]["id"], incentive_boost_active=True
            )
        )

        assert meta["total_count"] == 2
        assert set(ids_of(rows)) == {built["cell_b"]["id"], built["cell_c"]["id"]}
        assert {row["incentive_boost_active"] for row in rows} == {True}
        assert {row["effective_incentive_multiplier"] for row in rows} == {1.25}

    def test_boost_filter_is_not_a_constant_predicate(self, panel: PanelHarness):
        """`incentive_boost_active` false finds the one cell whose fill disarmed it.

        PRD 3.1: "When the graded status is anything other than `UNDER_TARGET` and
        the cell's boost is currently armed, `incentive_boost_active` becomes false,
        `effective_incentive_multiplier` returns to 1.00".

        Design: Corner/endpoints/quota_cell_listing_filters_by_market_status_and_boost_flag
        """
        built = _listing_markets(panel)

        rows, meta = validate_paginated(
            panel.client.list_quota_cells(
                panel.ops, market_id=built["market"]["id"], incentive_boost_active=False
            )
        )

        assert meta["total_count"] == 1
        assert ids_of(rows) == [built["cell_a"]["id"]]
        assert rows[0]["incentive_boost_active"] is False
        assert rows[0]["effective_incentive_multiplier"] == 1.0

    def test_pagination_counts_the_filtered_set_and_pages_disjointly(
        self, panel: PanelHarness
    ):
        """`limit` and `offset` layered on a filter count 2, not the 4-row table.

        PRD 2.3: "`limit` caps the number of rows returned; when omitted it defaults
        to 10, its minimum accepted value is 1 and its maximum accepted value is 100.
        `offset` is the number of rows to skip before the page begins and defaults to 0."

        PRD 2.3: "`total_count` (the number of rows the filter matched before
        pagination) and `has_more` (true when rows remain beyond this page)".

        Design: Corner/endpoints/quota_cell_listing_filters_by_market_status_and_boost_flag
        """
        built = _listing_markets(panel)

        page_one, meta_one = validate_paginated(
            panel.client.list_quota_cells(
                panel.ops,
                market_id=built["market"]["id"],
                quota_status="UNDER_TARGET",
                limit=1,
                offset=0,
            )
        )
        page_two, meta_two = validate_paginated(
            panel.client.list_quota_cells(
                panel.ops,
                market_id=built["market"]["id"],
                quota_status="UNDER_TARGET",
                limit=1,
                offset=1,
            )
        )

        assert len(page_one) == 1
        assert meta_one["total_count"] == 2
        assert meta_one["limit"] == 1
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True

        assert len(page_two) == 1
        assert meta_two["total_count"] == 2
        assert meta_two["offset"] == 1
        assert meta_two["has_more"] is False

        assert page_one[0]["id"] != page_two[0]["id"]
        assert set(ids_of(page_one + page_two)) == {
            built["cell_b"]["id"],
            built["cell_c"]["id"],
        }

    def test_unfiltered_listing_spans_both_markets(self, panel: PanelHarness):
        """The other market's filter sees one cell; no filter at all sees all four.

        PRD 2.3: "Each collection also accepts optional equality filters, all of them
        independent and combinable".

        PRD 2.1: "All seven roles may advance the logical clock, and all seven roles
        may read markets, quota cells, universe vintages, editing rule sets,
        households, meters, processing runs, clients, deliverables, notifications and
        accreditation audits."

        Design: Corner/endpoints/quota_cell_listing_filters_by_market_status_and_boost_flag
        """
        built = _listing_markets(panel)

        scoped, scoped_meta = validate_paginated(
            panel.client.list_quota_cells(
                panel.ops, market_id=built["other_market"]["id"]
            )
        )
        assert scoped_meta["total_count"] == 1
        assert ids_of(scoped) == [built["other_cell"]["id"]]

        every, every_meta = validate_paginated(
            panel.client.list_quota_cells(panel.auditor)
        )
        assert every_meta["total_count"] == 4
        assert set(ids_of(every)) == {
            built["cell_a"]["id"],
            built["cell_b"]["id"],
            built["cell_c"]["id"],
            built["other_cell"]["id"],
        }

    def test_single_cell_read_reports_the_filled_grade(self, panel: PanelHarness):
        """The row the boolean filter separated reads back FILLED at fill rate 1.0000.

        PRD 3.1: "`intab_count` is recounted as the number of households of that cell
        whose `status` is exactly `ACTIVE`".

        PRD 3.1: "`fill_rate` is then the in-tab count divided by `target_households`,
        rounded half up to 4 decimal places."

        Design: Corner/endpoints/quota_cell_listing_filters_by_market_status_and_boost_flag
        """
        built = _listing_markets(panel)

        cell = validate_success(
            panel.client.get_quota_cell(panel.auditor, built["cell_a"]["id"]), 200
        )

        assert cell["id"] == built["cell_a"]["id"]
        assert cell["intab_count"] == 1
        assert cell["fill_rate"] == 1.0
        assert cell["quota_status"] == "FILLED"
        assert cell["incentive_boost_active"] is False
        assert cell["effective_incentive_multiplier"] == 1.0


# ======================================================================
# GET /tuning-intervals and GET /tuning-intervals/{tuning_interval_id}
# ======================================================================

def _two_meter_panel(panel: PanelHarness) -> dict:
    """One ACTIVE home holding a TV_TUNER and a STREAMING_ROUTER, with three blocks.

    Both devices are shipped before either install is confirmed, because PRD 3.3
    admits a shipment only while the household is `RECRUITED` or
    `INSTALL_SCHEDULED` and confirming the tuner moves the home on to
    `ENUM_PENDING`. The clock is then advanced to 2026-08-05T00:00:00Z so every
    block's `end_iso` is in the past.
    """
    market = panel.create_market(
        name="Metro Records", dma_rank=183, incentive_budget_cents=500000
    )
    cell = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=4,
        base_incentive_cents=1000,
    )
    household = panel.recruit_household(market["id"], cell["id"], persons_count=2)
    tuner = panel.ship_meter(household["id"], meter_type="TV_TUNER")
    router = panel.ship_meter(household["id"], meter_type="STREAMING_ROUTER")
    panel.install_meter(tuner["id"])
    panel.install_meter(router["id"])
    panel.enumerate_household(
        household["id"], roster_persons_count=2, tv_sets_count=1
    )
    panel.set_clock(CLOCK_AUG_05)
    first = panel.ingest_interval(
        tuner["id"],
        household["id"],
        "2026-08-03T01:00:00Z",
        "2026-08-03T02:00:00Z",
        60,
        station_code="WAAA",
    )
    second = panel.ingest_interval(
        tuner["id"],
        household["id"],
        "2026-08-04T01:00:00Z",
        "2026-08-04T02:00:00Z",
        60,
        station_code="WAAA",
    )
    streamed = panel.ingest_interval(
        router["id"],
        household["id"],
        "2026-08-04T03:00:00Z",
        "2026-08-04T04:00:00Z",
        45,
        source_methodology="STREAMING_SDK",
        station_code="WCCC",
    )
    return {
        "market": market,
        "cell": cell,
        "household": household,
        "tuner": tuner,
        "router": router,
        "first": first,
        "second": second,
        "streamed": streamed,
    }


class TestTuningIntervalListing:
    """The confidential interval listing: meter, household, state, methodology, ascribed."""

    def test_household_filter_reaches_both_meters_in_start_order(
        self, panel: PanelHarness
    ):
        """The household filter spans both devices and pages in `start_iso` order.

        PRD 2.3: "Tuning intervals: `meter_id`, `household_id`, `processing_run_id`,
        `state`, `source_methodology`, `ascribed`."

        PRD 2.3: "Tuning intervals are ordered by `start_iso` ascending, ties broken
        by `created_at` ascending."

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        rows, meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician, household_id=built["household"]["id"]
            )
        )

        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(rows) == 3
        assert ids_of(rows) == [
            built["first"]["id"],
            built["second"]["id"],
            built["streamed"]["id"],
        ]
        assert_ordered_by(rows, [("start_iso", "asc"), ("created_at", "asc")])

    def test_meter_filter_is_narrower_than_the_household_filter(
        self, panel: PanelHarness
    ):
        """The tuner's own filter drops the router's block.

        PRD 2.3: "Tuning intervals: `meter_id`, `household_id`, `processing_run_id`,
        `state`, `source_methodology`, `ascribed`."

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        rows, meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician, meter_id=built["tuner"]["id"]
            )
        )

        assert meta["total_count"] == 2
        assert set(ids_of(rows)) == {built["first"]["id"], built["second"]["id"]}
        assert {row["meter_id"] for row in rows} == {built["tuner"]["id"]}

    def test_methodology_filter_selects_the_streaming_block(self, panel: PanelHarness):
        """`source_methodology` STREAMING_SDK matches only the router's record.

        PRD 3.6: "`source_methodology` must match the meter's `meter_type` under a
        fixed mapping — `TV_TUNER` collects `INHOME_TUNER`, `STREAMING_ROUTER`
        collects `STREAMING_SDK`, and `PORTABLE_OOH` collects `PORTABLE_OOH`".

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        rows, meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician, source_methodology="STREAMING_SDK"
            )
        )

        assert meta["total_count"] == 1
        assert ids_of(rows) == [built["streamed"]["id"]]
        assert rows[0]["meter_id"] == built["router"]["id"]

    def test_state_filter_finds_every_row_raw_and_none_edited(self, panel: PanelHarness):
        """Nothing has been run, so `state` RAW matches all three and EDITED none.

        PRD 3.6: "An ingested record starts at `state` `RAW` with `usable_minutes` 0,
        `ascribed` false, and `processing_run_id` and `invalidation_reason` both null."

        PRD 2.3: "`total_count` (the number of rows the filter matched before
        pagination)".

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        raw_rows, raw_meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician, household_id=built["household"]["id"], state="RAW"
            )
        )
        assert raw_meta["total_count"] == 3
        assert {row["state"] for row in raw_rows} == {"RAW"}

        edited_rows, edited_meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician,
                household_id=built["household"]["id"],
                state="EDITED",
            )
        )
        assert edited_meta["total_count"] == 0
        assert edited_rows == []

    def test_ascribed_filter_finds_nothing_before_an_edit_pass(
        self, panel: PanelHarness
    ):
        """No record is synthetic until the edit pass ascribes one.

        PRD 3.6: "An ingested record starts at `state` `RAW` with `usable_minutes` 0,
        `ascribed` false, and `processing_run_id` and `invalidation_reason` both null."

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        rows, meta = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician,
                household_id=built["household"]["id"],
                ascribed=True,
            )
        )

        assert meta["total_count"] == 0
        assert rows == []

    def test_pagination_walks_to_a_short_final_page(self, panel: PanelHarness):
        """Two per page leaves a one-row third page whose `has_more` is false.

        PRD 2.3: "`offset` is the number of rows to skip before the page begins and
        defaults to 0."

        PRD 2.3: "`total_count` (the number of rows the filter matched before
        pagination) and `has_more` (true when rows remain beyond this page)".

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        page_one, meta_one = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician,
                household_id=built["household"]["id"],
                limit=2,
                offset=0,
            )
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True

        page_two, meta_two = validate_paginated(
            panel.client.list_tuning_intervals(
                panel.statistician,
                household_id=built["household"]["id"],
                limit=2,
                offset=2,
            )
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["offset"] == 2
        assert meta_two["has_more"] is False
        assert ids_of(page_two) == [built["streamed"]["id"]]

    def test_single_interval_read_pins_the_pre_edit_defaults(self, panel: PanelHarness):
        """The router's record reads back RAW, uncredited, unclaimed and not ascribed.

        PRD 3.6: "An ingested record starts at `state` `RAW` with `usable_minutes` 0,
        `ascribed` false, and `processing_run_id` and `invalidation_reason` both null."

        PRD 2.1: "tuning intervals and household weights may only be read by a
        `PanelOperationsManager`, a `MethodologyStatistician` or an
        `AccreditationAuditor`."

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        record = validate_success(
            panel.client.get_tuning_interval(panel.auditor, built["streamed"]["id"]), 200
        )

        assert record["meter_id"] == built["router"]["id"]
        assert record["household_id"] == built["household"]["id"]
        assert record["source_methodology"] == "STREAMING_SDK"
        assert record["tuning_minutes"] == 45
        assert record["usable_minutes"] == 0
        assert record["state"] == "RAW"
        assert record["processing_run_id"] is None
        assert record["invalidation_reason"] is None
        assert record["ascribed"] is False

    def test_ingest_refreshed_the_rolling_compliance_snapshot(
        self, panel: PanelHarness
    ):
        """Two reported days, both above the floor, leave the rolling rate at 1.0000.

        PRD 3.6: "The evaluated days are the count of distinct UTC calendar dates
        inside that window on which the household holds at least one interval in
        `state` `RAW`, `EDITED` or `ASCRIBED` — **reported days only**".

        PRD 3.6: "A day is compliant when the household's minutes credited to that UTC
        calendar date reach at least 30".

        PRD 3.6: "The figure is stored, not derived at read time: it is recomputed on
        interval ingest and on a fault-detection scan".

        Design: Corner/endpoints/tuning_interval_listing_filters_by_meter_household_state_and_methodology
        """
        built = _two_meter_panel(panel)

        household = panel.read_household(built["household"]["id"])

        assert household["compliance_rate_rolling_30"] == 1.0


# ======================================================================
# GET /household-weights and GET /household-weights/{household_weight_id}
# ======================================================================

def _weighted_panel(panel: PanelHarness) -> dict:
    """A PUBLISHED FINAL run whose single contributor reported 350 minutes.

    The cell population is 100000 households and the run window is 1440 minutes,
    so the FINAL denominator is the one contributing household, the base weight
    is 100000.0000 and nothing is capped.
    """
    base = panel.published_run(
        household_specs=[{"intervals": [(WINDOW_START, "2026-08-01T06:00:00Z", 350)]}]
    )
    base["household"] = base["households"][0]["household"]
    return base


class TestHouseholdWeightRead:
    """The weight row as a read-only projection of one weighting pass."""

    def test_one_row_per_contributing_household(self, panel: PanelHarness):
        """The run filter finds exactly one weight row, for the household that reported.

        PRD 3.7: "One `HouseholdWeight` row is written per household holding at least
        one tuning interval of this run in `state` `EDITED` or `ASCRIBED` with
        `usable_minutes` above 0."

        PRD 2.3: "Household weights: `processing_run_id`, `household_id`, `capped`,
        `weight_variant`."

        Design: Corner/endpoints/household_weight_read_matches_the_weighting_pass
        """
        base = _weighted_panel(panel)

        rows, meta = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician, processing_run_id=base["run"]["id"]
            )
        )

        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["processing_run_id"] == base["run"]["id"]
        assert rows[0]["household_id"] == base["household"]["id"]

    def test_row_reports_the_final_base_and_adjusted_weight(self, panel: PanelHarness):
        """Population 100000 over a FINAL denominator of one contributor, uncapped.

        PRD 3.7: "The `base_weight` is that cell population divided by a
        variant-specific denominator, rounded half up to 4 decimal places."

        PRD 3.7: "Under `FINAL`, the denominator is the number of households of that
        cell that actually contributed at least one `EDITED` or `ASCRIBED` interval to
        **this** run with `usable_minutes` above 0."

        PRD 3.7: "If there are no capped rows, every row's `adjusted_weight` equals its
        `base_weight` and the run's `total_weight_mass` is the mass."

        PRD 2.1: "tuning intervals and household weights may only be read by a
        `PanelOperationsManager`, a `MethodologyStatistician` or an
        `AccreditationAuditor`."

        Design: Corner/endpoints/household_weight_read_matches_the_weighting_pass
        """
        base = _weighted_panel(panel)
        listed, _ = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician, processing_run_id=base["run"]["id"]
            )
        )

        row = validate_success(
            panel.client.get_household_weight(panel.auditor, listed[0]["id"]), 200
        )

        assert row["processing_run_id"] == base["run"]["id"]
        assert row["weight_variant"] == "FINAL"
        assert row["base_weight"] == 100000.0
        assert row["adjusted_weight"] == 100000.0
        assert row["capped"] is False
        assert row["usable_minutes"] == 350

    def test_contribution_is_the_weight_over_the_window(self, panel: PanelHarness):
        """350 credited minutes of a 1440-minute window price the row at 24305.56.

        PRD 3.7: "First, each household's `contribution` is its `adjusted_weight`
        multiplied by its summed usable minutes and divided by the run's
        `window_minutes`, rounded half up to 2 decimal places."

        Design: Corner/endpoints/household_weight_read_matches_the_weighting_pass
        """
        base = _weighted_panel(panel)

        rows, _ = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician, processing_run_id=base["run"]["id"]
            )
        )

        assert rows[0]["contribution"] == expected_contribution(
            100000.0, 350, WINDOW_MINUTES
        )
        assert rows[0]["contribution"] == 24305.56

    def test_run_compliance_rate_reads_every_day_of_the_window(
        self, panel: PanelHarness
    ):
        """One evaluated day, 350 credited minutes on it, so the run-scoped rate is 1.0000.

        PRD 3.7: "Its evaluated days are **every** calendar day of the run window —
        the run's `window_minutes` divided by 1440 and rounded up — whether the
        household reported on that day or not".

        PRD 3.7: "And it reads only records in `state` `EDITED` or `ASCRIBED` whose
        `processing_run_id` is this run, using their credited `usable_minutes`".

        Design: Corner/endpoints/household_weight_read_matches_the_weighting_pass
        """
        base = _weighted_panel(panel)

        rows, _ = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician, processing_run_id=base["run"]["id"]
            )
        )

        assert rows[0]["run_compliance_rate"] == 1.0

    def test_variant_filter_matches_the_stored_variant(self, panel: PanelHarness):
        """FINAL finds the row and DESIGN finds nothing; the filter is not a constant.

        PRD 2.3: "Household weights: `processing_run_id`, `household_id`, `capped`,
        `weight_variant`."

        PRD 3.7: "Each row copies the owning run's `weight_variant`".

        Design: Corner/endpoints/household_weight_read_matches_the_weighting_pass
        """
        base = _weighted_panel(panel)

        final_rows, final_meta = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician,
                processing_run_id=base["run"]["id"],
                weight_variant="FINAL",
            )
        )
        assert final_meta["total_count"] == 1
        assert final_rows[0]["weight_variant"] == "FINAL"

        _, design_meta = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician,
                processing_run_id=base["run"]["id"],
                weight_variant="DESIGN",
            )
        )
        assert design_meta["total_count"] == 0

    def test_capped_filter_discriminates(self, panel: PanelHarness):
        """`capped` true finds nothing while the household plus `capped` false finds the row.

        PRD 3.7: "Rows whose `base_weight` is **strictly greater** than the cap are the
        capped rows; a row exactly at the cap is not capped."

        PRD 2.3: "Household weights: `processing_run_id`, `household_id`, `capped`,
        `weight_variant`."

        Design: Corner/endpoints/household_weight_read_matches_the_weighting_pass
        """
        base = _weighted_panel(panel)

        _, capped_meta = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician, processing_run_id=base["run"]["id"], capped=True
            )
        )
        assert capped_meta["total_count"] == 0

        uncapped_rows, uncapped_meta = validate_paginated(
            panel.client.list_household_weights(
                panel.statistician,
                household_id=base["household"]["id"],
                capped=False,
            )
        )
        assert uncapped_meta["total_count"] == 1
        assert uncapped_rows[0]["household_id"] == base["household"]["id"]

    def test_unknown_weight_id_is_a_not_found(self, panel: PanelHarness):
        """A well-formed id that was never minted is a 404, not an empty row.

        PRD 2.6: "Failures at step 4 and step 5 are reported with the not-found error
        of the entity whose identifier failed: ... `ERR_HOUSEHOLD_WEIGHT_NOT_FOUND`
        ... each at HTTP 404."

        Design: Corner/endpoints/household_weight_read_matches_the_weighting_pass
        """
        _weighted_panel(panel)

        validate_error(
            panel.client.get_household_weight(panel.statistician, MISSING_UUID),
            "ERR_HOUSEHOLD_WEIGHT_NOT_FOUND",
        )


# ======================================================================
# GET /client-deliverables and the two creation routes
# ======================================================================

def _deliverable_pair(panel: PanelHarness) -> dict:
    """A PREMIUM subscriber of a PUBLISHED run holding one row of each kind.

    The clock stands at 2026-08-02T00:00:00Z, so both rows take the PREMIUM
    24-hour service level from that instant.
    """
    base = panel.subscribed_published_run(tier="PREMIUM")
    client = base["client"]
    base["scheduled"] = panel.schedule_deliverable(
        client["id"], base["run"]["id"], requested_cell_count=2
    )
    base["custom"] = panel.request_custom_analysis(
        client["id"],
        base["run"]["id"],
        question="Rank the top five stations by 18-34 reach",
        requested_cell_count=3,
    )
    return base


def _held_deliverable_pair(panel: PanelHarness) -> dict:
    """The same pair with the scheduled row held for a data-quality review."""
    base = _deliverable_pair(panel)
    base["hold"] = validate_success(
        panel.client.hold_deliverable(
            panel.rep, base["scheduled"]["id"], hold_reason="DATA_QUALITY_REVIEW"
        ),
        200,
    )
    return base


class TestClientDeliverableListing:
    """Two creation routes, one collection: `kind`, `state` and `hold_reason`."""

    def test_scheduled_row_starts_unpriced_and_takes_the_tier_sla(
        self, panel: PanelHarness
    ):
        """A placement against a published run is SCHEDULED, at zero cents, due in 24 hours.

        PRD 3.8: "The row is created with `kind` `SCHEDULED_DATASET`, `state`
        `SCHEDULED`, `question` null, `revision_count` 0, `gross_cents` 0 and
        `total_cents` 0."

        PRD 3.8: "Its `due_at` is set immediately to the logical clock plus the
        client's `delivery_sla_hours` when the pinned run is already `PUBLISHED`".

        PRD 3.8: "`PREMIUM` sets `tier_base_fee_cents` to 120000, `delivery_sla_hours`
        to 24 and `custom_analysis_quota` to 10."

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _deliverable_pair(panel)

        row = base["scheduled"]

        assert row["kind"] == "SCHEDULED_DATASET"
        assert row["state"] == "SCHEDULED"
        assert row["question"] is None
        assert row["requested_cell_count"] == 2
        assert row["gross_cents"] == 0
        assert row["total_cents"] == 0
        assert row["revision_count"] == 0
        assert _instant(row["due_at"]) == _instant(CLOCK_T1) + timedelta(
            hours=PREMIUM_SLA_HOURS
        )

    def test_custom_analysis_starts_requested_with_its_question(
        self, panel: PanelHarness
    ):
        """The other creation route lands REQUESTED, carries the question and is due too.

        PRD 3.8: "The row is created with `kind` `CUSTOM_ANALYSIS` and `state`
        `REQUESTED` — not the machine's declared initial state — its `due_at` set to
        the logical clock plus the client's `delivery_sla_hours`, and the client's
        `custom_analysis_used` raised by one."

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _deliverable_pair(panel)

        row = base["custom"]

        assert row["kind"] == "CUSTOM_ANALYSIS"
        assert row["state"] == "REQUESTED"
        assert row["question"] == "Rank the top five stations by 18-34 reach"
        assert row["requested_cell_count"] == 3
        assert _instant(row["due_at"]) == _instant(CLOCK_T1) + timedelta(
            hours=PREMIUM_SLA_HOURS
        )

    def test_hold_records_the_state_it_was_held_from(self, panel: PanelHarness):
        """Holding the scheduled row stores HELD over a remembered SCHEDULED.

        PRD 3.8: "The hold records `held_from_state` as the state the row occupied
        immediately before the hold, sets `state` to `HELD`, and raises the client's
        `held_deliverable_count` by one."

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _held_deliverable_pair(panel)

        assert base["hold"]["state"] == "HELD"
        assert base["hold"]["held_from_state"] == "SCHEDULED"
        assert base["hold"]["hold_reason"] == "DATA_QUALITY_REVIEW"

    def test_client_filter_lists_both_kinds_in_created_order(self, panel: PanelHarness):
        """The client filter returns both rows, ordered by `created_at` ascending.

        PRD 2.3: "Client deliverables: `client_id`, `processing_run_id`, `kind`,
        `state`, `hold_reason`."

        PRD 2.3: "Unless a collection states otherwise below, list results are ordered
        by `created_at` ascending."

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _deliverable_pair(panel)

        rows, meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, client_id=base["client"]["id"]
            )
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert set(ids_of(rows)) == {base["scheduled"]["id"], base["custom"]["id"]}
        assert_ordered_by(rows, [("created_at", "asc")])

    def test_kind_filter_separates_the_two_creation_routes(self, panel: PanelHarness):
        """Each `kind` value matches exactly the row its own endpoint created.

        PRD 2.3: "Client deliverables: `client_id`, `processing_run_id`, `kind`,
        `state`, `hold_reason`."

        PRD 3.8: "A `ClientDeliverable` is polymorphic and its `kind` is fixed at
        creation; no transition ever converts one kind into the other."

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _deliverable_pair(panel)

        custom_rows, custom_meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, client_id=base["client"]["id"], kind="CUSTOM_ANALYSIS"
            )
        )
        assert custom_meta["total_count"] == 1
        assert ids_of(custom_rows) == [base["custom"]["id"]]

        scheduled_rows, scheduled_meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, client_id=base["client"]["id"], kind="SCHEDULED_DATASET"
            )
        )
        assert scheduled_meta["total_count"] == 1
        assert ids_of(scheduled_rows) == [base["scheduled"]["id"]]

    def test_state_filter_finds_only_the_held_row(self, panel: PanelHarness):
        """`state` HELD matches the held placement and not the untouched analysis.

        PRD 2.3: "Client deliverables: `client_id`, `processing_run_id`, `kind`,
        `state`, `hold_reason`."

        PRD 3.8: "The hold records `held_from_state` as the state the row occupied
        immediately before the hold, sets `state` to `HELD`".

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _held_deliverable_pair(panel)

        rows, meta = validate_paginated(
            panel.client.list_client_deliverables(panel.rep, state="HELD")
        )

        assert meta["total_count"] == 1
        assert ids_of(rows) == [base["scheduled"]["id"]]

    def test_hold_reason_filter_discriminates_within_the_held_state(
        self, panel: PanelHarness
    ):
        """The reason the row was held is a filter of its own, and the other value is empty.

        PRD 2.3: "Client deliverables: `client_id`, `processing_run_id`, `kind`,
        `state`, `hold_reason`."

        PRD 3.8: "A `ClientServiceRep` puts a non-terminal deliverable on hold by
        supplying a `hold_reason` of `CLIENT_REQUESTED` or `DATA_QUALITY_REVIEW`."

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _held_deliverable_pair(panel)

        quality_rows, quality_meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, hold_reason="DATA_QUALITY_REVIEW"
            )
        )
        assert quality_meta["total_count"] == 1
        assert ids_of(quality_rows) == [base["scheduled"]["id"]]

        _, requested_meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, hold_reason="CLIENT_REQUESTED"
            )
        )
        assert requested_meta["total_count"] == 0

    def test_run_filter_paginates_over_both_rows(self, panel: PanelHarness):
        """One row per page over the run's two deliverables leaves `has_more` true.

        PRD 2.3: "Client deliverables: `client_id`, `processing_run_id`, `kind`,
        `state`, `hold_reason`."

        PRD 2.3: "`total_count` (the number of rows the filter matched before
        pagination) and `has_more` (true when rows remain beyond this page)".

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _deliverable_pair(panel)

        rows, meta = validate_paginated(
            panel.client.list_client_deliverables(
                panel.rep, processing_run_id=base["run"]["id"], limit=1, offset=0
            )
        )

        assert len(rows) == 1
        assert meta["total_count"] == 2
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is True

    def test_only_the_custom_analysis_consumed_quota_and_the_hold_earned_no_credit(
        self, panel: PanelHarness
    ):
        """The subscriber's counters move once each, and a quality hold pays nothing.

        PRD 3.8: "the client's `custom_analysis_used` raised by one."

        PRD 3.8: "A service-level credit of 5 percent of the client's
        `tier_base_fee_cents`, rounded to a whole cent, is added to
        `delivery_sla_credit_cents` **only** when the `hold_reason` is
        `UPSTREAM_RUN_REPIN`".

        Design: Corner/endpoints/client_deliverable_listing_filters_by_kind_state_and_hold_reason
        """
        base = _held_deliverable_pair(panel)

        client = panel.read_client(base["client"]["id"])

        assert client["custom_analysis_used"] == 1
        assert client["held_deliverable_count"] == 1
        assert client["delivery_sla_credit_cents"] == 0


# ======================================================================
# The two deliverable creation endpoints against an unpublished run
# ======================================================================

def _rerun_pair(panel: PanelHarness) -> dict:
    """Two runs over one byte-identical window, so the first is SUPERSEDED.

    Neither run is ever edited, weighted or published, which is what lets a
    contractual placement sit against run B while a custom analysis cannot.
    """
    base = panel.panel_with_data(
        household_specs=[{"intervals": [(WINDOW_START, "2026-08-01T10:00:00Z", 600)]}]
    )
    base["run_a"] = panel.open_run_over(base)
    base["run_b"] = panel.open_run_over(base)
    base["client"] = panel.create_client(
        [base["market"]["id"]], tier="STANDARD", name="Seaboard Networks"
    )
    base["other_market"] = panel.create_market(
        name="Metro Uncontracted", dma_rank=187, incentive_budget_cents=500000
    )
    base["uncontracted"] = panel.create_client(
        [base["other_market"]["id"]], tier="BASIC", name="Inland Cable"
    )
    return base


class TestScheduledPlacementRunStates:
    """A placement tolerates every run state but `SUPERSEDED`; an analysis does not."""

    def test_identical_window_rerun_supersedes_the_open_run(self, panel: PanelHarness):
        """A byte-identical window is a re-run, and the older OPEN run is retired.

        PRD 3.6: "A byte-identical window is the single exception to the overlap rule:
        it is accepted and supersedes the older run — unless that older run is
        `PUBLISHED`, in which case the identical window is rejected exactly like any
        other overlap".

        PRD 3.6: "Any earlier run of the same market standing in `OPEN`, `EDITED`,
        `WEIGHTED` or `PENDING_REPIN` whose `window_start_iso` and `window_end_iso`
        both equal the new run's moves to `SUPERSEDED`, with `superseded_by_run_id`
        set to the new run's identifier."

        PRD 2.5: "Timestamps that record a business event rather than a row edit —
        `recruited_at`, `installed_at`, `last_enumeration_at`, `published_at`,
        `superseded_at` ... are all read from the logical clock at the moment the event
        occurs".

        Design: Corner/endpoints/scheduled_placement_accepts_an_unpublished_run_but_never_a_superseded_one
        """
        base = _rerun_pair(panel)

        assert base["run_b"]["state"] == "OPEN"

        retired = panel.read_run(base["run_a"]["id"])
        assert retired["state"] == "SUPERSEDED"
        assert retired["superseded_by_run_id"] == base["run_b"]["id"]

    def test_placement_against_a_superseded_run_is_refused(self, panel: PanelHarness):
        """A schedule can never be pinned to a run that has been re-run away.

        PRD 3.8: "and the run's `state` must not be `SUPERSEDED`, otherwise
        `ERR_RUN_SUPERSEDED`."

        Design: Corner/endpoints/scheduled_placement_accepts_an_unpublished_run_but_never_a_superseded_one
        """
        base = _rerun_pair(panel)

        validate_error(
            panel.client.create_scheduled_deliverable(
                panel.rep,
                base["client"]["id"],
                processing_run_id=base["run_a"]["id"],
                requested_cell_count=1,
            ),
            "ERR_RUN_SUPERSEDED",
        )

    def test_placement_against_an_open_run_is_accepted_with_no_deadline(
        self, panel: PanelHarness
    ):
        """The live run has not published, so the row is SCHEDULED with `due_at` null.

        PRD 3.8: "Crucially, **any** other run state is accepted — delivery schedules
        are set in advance, so a placement may sit against a run that has not published
        and is still editable."

        PRD 3.8: "Its `due_at` is set immediately to the logical clock plus the client's
        `delivery_sla_hours` when the pinned run is already `PUBLISHED`, and is
        otherwise left null until that run publishes."

        Design: Corner/endpoints/scheduled_placement_accepts_an_unpublished_run_but_never_a_superseded_one
        """
        base = _rerun_pair(panel)

        row = validate_success(
            panel.client.create_scheduled_deliverable(
                panel.rep,
                base["client"]["id"],
                processing_run_id=base["run_b"]["id"],
                requested_cell_count=1,
            ),
            201,
        )

        assert row["kind"] == "SCHEDULED_DATASET"
        assert row["state"] == "SCHEDULED"
        assert row["due_at"] is None
        assert row["gross_cents"] == 0
        assert row["total_cents"] == 0

    def test_contract_check_outranks_the_run_state_for_a_placement(
        self, panel: PanelHarness
    ):
        """A client contracted to the wrong market is refused on entitlement, at 403.

        PRD 3.8: "Three checks run in this order: the client's `status` must not be
        `SUSPENDED`, otherwise `ERR_CLIENT_SUSPENDED`; the run's `market_id` must appear
        in the client's `contract_market_ids`, otherwise `ERR_MARKET_NOT_CONTRACTED`
        (HTTP 403, because this is a contractual entitlement failure rather than a state
        failure); and the run's `state` must not be `SUPERSEDED`, otherwise
        `ERR_RUN_SUPERSEDED`."

        Design: Corner/endpoints/scheduled_placement_accepts_an_unpublished_run_but_never_a_superseded_one
        """
        base = _rerun_pair(panel)

        validate_error(
            panel.client.create_scheduled_deliverable(
                panel.rep,
                base["uncontracted"]["id"],
                processing_run_id=base["run_b"]["id"],
                requested_cell_count=1,
            ),
            "ERR_MARKET_NOT_CONTRACTED",
        )

    def test_contract_check_outranks_the_run_state_and_the_quota(
        self, panel: PanelHarness
    ):
        """The uncontracted BASIC client hears about the contract, not the run or its quota.

        PRD 3.8: "Four checks run in this order: the client must not be `SUSPENDED`
        (`ERR_CLIENT_SUSPENDED`); the run's market must be contracted
        (`ERR_MARKET_NOT_CONTRACTED`); the run's `state` must be `PUBLISHED`, otherwise
        `ERR_RUN_NOT_PUBLISHED`; and the client's `custom_analysis_used` must be
        strictly below its `custom_analysis_quota`, otherwise
        `ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED`."

        PRD 3.8: "A `BASIC` client has a quota of 0 and can therefore never file one."

        Design: Corner/endpoints/scheduled_placement_accepts_an_unpublished_run_but_never_a_superseded_one
        """
        base = _rerun_pair(panel)

        validate_error(
            panel.client.create_custom_analysis(
                panel.rep,
                client_id=base["uncontracted"]["id"],
                processing_run_id=base["run_b"]["id"],
                question="Share of viewing by daypart",
                requested_cell_count=1,
            ),
            "ERR_MARKET_NOT_CONTRACTED",
        )

    def test_custom_analysis_demands_a_published_run(self, panel: PanelHarness):
        """The contracted client clears the contract gate and hits the run-state gate.

        PRD 3.8: "the run's `state` must be `PUBLISHED`, otherwise
        `ERR_RUN_NOT_PUBLISHED`".

        PRD 3.8: "A **custom analysis** is a bespoke question against data already
        published."

        Design: Corner/endpoints/scheduled_placement_accepts_an_unpublished_run_but_never_a_superseded_one
        """
        base = _rerun_pair(panel)

        validate_error(
            panel.client.create_custom_analysis(
                panel.rep,
                client_id=base["client"]["id"],
                processing_run_id=base["run_b"]["id"],
                question="Share of viewing by daypart",
                requested_cell_count=1,
            ),
            "ERR_RUN_NOT_PUBLISHED",
        )


# ======================================================================
# POST /_clock/set_current_utc
# ======================================================================

def _clock_market(panel: PanelHarness) -> dict:
    """A bare market with one cell plus a subscriber, all built at the startup clock."""
    market = panel.create_market(
        name="Metro Clock", dma_rank=188, incentive_budget_cents=500000
    )
    cell = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=4,
        base_incentive_cents=1000,
    )
    client = panel.create_client([market["id"]], tier="BASIC", name="Clockwork Media")
    return {"market": market, "cell": cell, "client": client}


class TestClockEndpoint:
    """The clock is monotonic with a `>=` comparison and open to every role."""

    def test_a_field_technician_may_advance_the_clock(self, panel: PanelHarness):
        """A role that owns none of the deadline arithmetic may still move time forward.

        PRD 2.4: "All seven roles may advance the clock, because every role's workflow
        needs to be able to move time forward."

        PRD 2.4: "an administrative test-driving capability sets that clock to a
        supplied `current_utc` instant, answering with the value now in force as
        `current_utc` and the value it replaced as `previous_utc`."

        Design: Corner/endpoints/clock_endpoint_is_monotonic_and_open_to_every_role
        """
        _clock_market(panel)

        moved = validate_success(
            panel.client.set_logical_clock(panel.tech, current_utc=CLOCK_AUG_05), 200
        )

        assert _instant(moved["current_utc"]) == _instant(CLOCK_AUG_05)
        assert _instant(moved["previous_utc"]) == _instant(CLOCK_T0)

    def test_a_client_user_may_reset_the_clock_to_its_current_value(
        self, panel: PanelHarness
    ):
        """Setting the clock to exactly the value in force satisfies the `>=` rule.

        PRD 2.4: "setting it to exactly the value already in force is accepted, since
        the requirement is that the new value be greater than or equal to the current
        one."

        PRD 2.1: "When `X-User-Role` is `ClientUser`, by contrast, `X-User-ID` is the
        `id` of the acting `Client` row".

        Design: Corner/endpoints/clock_endpoint_is_monotonic_and_open_to_every_role
        """
        built = _clock_market(panel)
        validate_success(
            panel.client.set_logical_clock(panel.tech, current_utc=CLOCK_AUG_05), 200
        )

        again = validate_success(
            panel.client.set_logical_clock(
                panel.client_headers(built["client"]["id"]), current_utc=CLOCK_AUG_05
            ),
            200,
        )

        assert _instant(again["current_utc"]) == _instant(CLOCK_AUG_05)
        assert _instant(again["previous_utc"]) == _instant(CLOCK_AUG_05)

    def test_one_second_backwards_is_refused(self, panel: PanelHarness):
        """A single second earlier than the value in force is not a monotonic move.

        PRD 2.4: "The clock is monotonic. A request whose `current_utc` is earlier than
        the value currently in force is rejected with `ERR_CLOCK_NOT_MONOTONIC`
        (HTTP 422)".

        Design: Corner/endpoints/clock_endpoint_is_monotonic_and_open_to_every_role
        """
        _clock_market(panel)
        validate_success(
            panel.client.set_logical_clock(panel.tech, current_utc=CLOCK_AUG_05), 200
        )

        validate_error(
            panel.client.set_logical_clock(
                panel.statistician, current_utc=CLOCK_AUG_04_LAST_SECOND
            ),
            "ERR_CLOCK_NOT_MONOTONIC",
        )

    def test_a_refused_call_leaves_the_clock_where_it_was(self, panel: PanelHarness):
        """A later business timestamp proves the rejection rolled nothing back.

        PRD 2.4: "Nothing in this domain reads wall-clock time. Enumeration due dates,
        household tenure, interval windows, universe vintage spacing, notification lead
        times, delivery service levels and lateness penalties all read a single
        server-held logical clock".

        PRD 3.2: "A recruited household begins at `status` `RECRUITED` with
        `recruited_at` stamped from the logical clock".

        Design: Corner/endpoints/clock_endpoint_is_monotonic_and_open_to_every_role
        """
        built = _clock_market(panel)
        validate_success(
            panel.client.set_logical_clock(panel.tech, current_utc=CLOCK_AUG_05), 200
        )
        validate_error(
            panel.client.set_logical_clock(
                panel.statistician, current_utc=CLOCK_AUG_04_LAST_SECOND
            ),
            "ERR_CLOCK_NOT_MONOTONIC",
        )

        household = panel.recruit_household(
            built["market"]["id"], built["cell"]["id"], persons_count=3
        )

        assert _instant(household["recruited_at"]) == _instant(CLOCK_AUG_05)

    def test_the_clock_may_jump_forward_by_any_amount(self, panel: PanelHarness):
        """Nothing caps the size of a forward move.

        PRD 2.4: "The clock is monotonic. A request whose `current_utc` is earlier than
        the value currently in force is rejected with `ERR_CLOCK_NOT_MONOTONIC`
        (HTTP 422); setting it to exactly the value already in force is accepted, since
        the requirement is that the new value be greater than or equal to the current
        one."

        PRD 2.4: "All seven roles may advance the clock, because every role's workflow
        needs to be able to move time forward."

        Design: Corner/endpoints/clock_endpoint_is_monotonic_and_open_to_every_role
        """
        _clock_market(panel)
        validate_success(
            panel.client.set_logical_clock(panel.tech, current_utc=CLOCK_AUG_05), 200
        )

        jumped = validate_success(
            panel.client.set_logical_clock(panel.auditor, current_utc=CLOCK_SEP_01), 200
        )

        assert _instant(jumped["current_utc"]) == _instant(CLOCK_SEP_01)
        assert _instant(jumped["previous_utc"]) == _instant(CLOCK_AUG_05)


# ======================================================================
# POST /accreditation-audits and GET /accreditation-audits
# ======================================================================

AUDIT_OPENER_USER_ID = "auditor-opener-89"
AUDITOR_NOTE = "Annual methodology review"


def _audit_base(panel: PanelHarness) -> dict:
    """One market with a cell plus the PUBLISHED rule set an audit can scope."""
    market = panel.create_market(
        name="Metro Audited", dma_rank=189, incentive_budget_cents=500000
    )
    cell = panel.create_quota_cell(
        market["id"],
        age_band="P18_34",
        income_band="MID",
        geo_zone="URBAN",
        target_households=4,
        base_incentive_cents=1000,
    )
    rule_set = panel.published_rule_set(
        label="RS-C80",
        missing_interval_ascription_minutes=60,
        invalid_tuning_max_minutes=900,
        outlier_household_minutes_cap=1200,
        outlier_weight_ratio_cap=2.5,
        fault_missing_minutes_threshold=1440,
    )
    return {"market": market, "cell": cell, "rule_set": rule_set}


class TestAuditCreationLinks:
    """The audit row joins a Market to an EditRuleSet, each resolved on its own."""

    def test_missing_market_reports_the_market(self, panel: PanelHarness):
        """An unminted `market_id` is the market's own not-found error.

        PRD 2.6: "**Body reference existence** — every reference identifier carried in
        a request body must resolve to an existing row: `market_id`, `quota_cell_id`,
        `universe_estimate_id`, `edit_rule_set_id`, `processing_run_id`, `client_id`,
        `baseline_processing_run_id`, `target_edit_rule_set_id`,
        `proposed_edit_rule_set_id`, `scope_edit_rule_set_id`, `meter_id`,
        `household_id` and `supersedes_change_id`."

        PRD 2.6: "Failures at step 4 and step 5 are reported with the not-found error of
        the entity whose identifier failed: `ERR_MARKET_NOT_FOUND` ... each at HTTP 404."

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        built = _audit_base(panel)

        validate_error(
            panel.client.create_accreditation_audit(
                panel.auditor,
                market_id=MISSING_UUID,
                scope_edit_rule_set_id=built["rule_set"]["id"],
                auditor_note=AUDITOR_NOTE,
            ),
            "ERR_MARKET_NOT_FOUND",
        )

    def test_missing_rule_set_is_resolved_independently(self, panel: PanelHarness):
        """The second reference fails on its own even though the first resolved.

        PRD 2.6: "a `target_edit_rule_set_id`, `proposed_edit_rule_set_id` or
        `scope_edit_rule_set_id` that does not resolve reports
        `ERR_EDIT_RULE_SET_NOT_FOUND`."

        PRD 3.9: "An `AccreditationAuditor` opens an **AccreditationAudit** of a
        market's methodology, supplying the `market_id`, the `scope_edit_rule_set_id`
        whose methodology is in scope, and an `auditor_note` of 1 to 400 characters
        recording the scope."

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        built = _audit_base(panel)

        validate_error(
            panel.client.create_accreditation_audit(
                panel.auditor,
                market_id=built["market"]["id"],
                scope_edit_rule_set_id=MISSING_UUID,
                auditor_note=AUDITOR_NOTE,
            ),
            "ERR_EDIT_RULE_SET_NOT_FOUND",
        )

    def test_both_missing_reports_the_earlier_reference(self, panel: PanelHarness):
        """With both links dangling the caller hears about `market_id`, the earlier input.

        PRD 2.6: "**Body reference existence** — every reference identifier carried in a
        request body must resolve to an existing row: `market_id`, `quota_cell_id`,
        `universe_estimate_id`, `edit_rule_set_id`, `processing_run_id`, `client_id`,
        `baseline_processing_run_id`, `target_edit_rule_set_id`,
        `proposed_edit_rule_set_id`, `scope_edit_rule_set_id`, `meter_id`,
        `household_id` and `supersedes_change_id`."

        PRD 2.6: "Every request walks a fixed ladder of generic checks before any
        endpoint-specific business rule is consulted, and the first failure on the ladder
        is the error the caller sees".

        PRD 3.9: "supplying the `market_id`, the `scope_edit_rule_set_id` whose
        methodology is in scope, and an `auditor_note` of 1 to 400 characters recording
        the scope."

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        _audit_base(panel)

        validate_error(
            panel.client.create_accreditation_audit(
                panel.auditor,
                market_id=MISSING_UUID,
                scope_edit_rule_set_id=MISSING_UUID,
                auditor_note=AUDITOR_NOTE,
            ),
            "ERR_MARKET_NOT_FOUND",
        )

    def test_opening_links_the_market_and_the_rule_set(self, panel: PanelHarness):
        """Both references resolve, so the audit opens carrying its two links.

        PRD 3.9: "The audit starts in `OPEN` with `opened_by_user_id` stamped from
        `X-User-ID`, `outcome`, `finalized_by_user_id` and `finalized_at` null, and
        `limitation_disclosures` empty."

        PRD 2.1: "The server records it where a rule requires an operator identity — as
        `opened_by_user_id` and `published_by_user_id` on a processing run, as
        `opened_by_user_id` and `finalized_by_user_id` on an accreditation audit".

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        built = _audit_base(panel)

        audit = validate_success(
            panel.client.create_accreditation_audit(
                make_auditor_headers(AUDIT_OPENER_USER_ID),
                market_id=built["market"]["id"],
                scope_edit_rule_set_id=built["rule_set"]["id"],
                auditor_note=AUDITOR_NOTE,
            ),
            201,
        )

        assert audit["state"] == "OPEN"
        assert audit["market_id"] == built["market"]["id"]
        assert audit["scope_edit_rule_set_id"] == built["rule_set"]["id"]
        assert audit["outcome"] is None
        assert audit["limitation_disclosures"] == []
        assert audit["opened_by_user_id"] == AUDIT_OPENER_USER_ID
        assert audit["finalized_by_user_id"] is None
        assert audit["finalized_at"] is None

    def test_listing_filters_by_market_and_state(self, panel: PanelHarness):
        """The freshly opened audit is visible under its market and its state.

        PRD 2.3: "Accreditation audits: `market_id`, `scope_edit_rule_set_id`, `state`,
        `outcome`."

        PRD 2.3: "`total_count` (the number of rows the filter matched before
        pagination) and `has_more` (true when rows remain beyond this page)".

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        built = _audit_base(panel)
        audit = panel.open_audit(
            built["market"]["id"], built["rule_set"]["id"], auditor_note=AUDITOR_NOTE
        )

        rows, meta = validate_paginated(
            panel.client.list_accreditation_audits(
                panel.auditor, market_id=built["market"]["id"], state="OPEN"
            )
        )

        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert ids_of(rows) == [audit["id"]]

    def test_scope_and_outcome_filters_combine_to_nothing(self, panel: PanelHarness):
        """The audit is in scope for the rule set but has no outcome to match yet.

        PRD 2.3: "Each collection also accepts optional equality filters, all of them
        independent and combinable".

        PRD 3.9: "The audit starts in `OPEN` with `opened_by_user_id` stamped from
        `X-User-ID`, `outcome`, `finalized_by_user_id` and `finalized_at` null".

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        built = _audit_base(panel)
        panel.open_audit(
            built["market"]["id"], built["rule_set"]["id"], auditor_note=AUDITOR_NOTE
        )

        rows, meta = validate_paginated(
            panel.client.list_accreditation_audits(
                panel.auditor,
                scope_edit_rule_set_id=built["rule_set"]["id"],
                outcome="ACCREDITED",
            )
        )

        assert meta["total_count"] == 0
        assert rows == []

    def test_unknown_audit_id_is_a_not_found(self, panel: PanelHarness):
        """A path identifier that resolves to nothing is the audit's own 404.

        PRD 2.6: "**Path existence** — every identifier embedded in the URL is resolved
        left to right".

        PRD 2.6: "Failures at step 4 and step 5 are reported with the not-found error of
        the entity whose identifier failed: ... `ERR_ACCREDITATION_AUDIT_NOT_FOUND`,
        each at HTTP 404."

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        built = _audit_base(panel)
        panel.open_audit(
            built["market"]["id"], built["rule_set"]["id"], auditor_note=AUDITOR_NOTE
        )

        validate_error(
            panel.client.get_accreditation_audit(panel.auditor, MISSING_UUID),
            "ERR_ACCREDITATION_AUDIT_NOT_FOUND",
        )

    def test_opening_the_audit_froze_the_market(self, panel: PanelHarness):
        """The link has a side effect: the market it names stops accepting intake.

        PRD 3.9: "Opening it raises the market's `open_audit_count` by one, which fires
        the first clause of the posture calculation and drives `recruitment_posture` to
        `FROZEN` with `posture_changed_at` updated — overriding every cell-level
        consideration."

        PRD 3.1: "If the market has at least one accreditation audit in state `OPEN` —
        that is, `open_audit_count` is 1 or more — the posture is `FROZEN`."

        Design: Corner/endpoints/audit_creation_links_two_entities_and_reports_the_earlier_missing_one
        """
        built = _audit_base(panel)
        panel.open_audit(
            built["market"]["id"], built["rule_set"]["id"], auditor_note=AUDITOR_NOTE
        )

        market = panel.read_market(built["market"]["id"])

        assert market["open_audit_count"] == 1
        assert market["recruitment_posture"] == "FROZEN"
