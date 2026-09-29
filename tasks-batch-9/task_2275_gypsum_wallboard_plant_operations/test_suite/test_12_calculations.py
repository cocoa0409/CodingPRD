"""Derived figures pinned one formula at a time: the hemihydrate split, the
speed-scaled tension, the three bundle rounding scales, the live-batch filter on
calciner capacity, the freight zone cut points, the free-water bands, the running
feed total, the seasonality table and the inclusive downgrade ceiling.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    ApiErrorId,
    BatchStatus,
    FailingAttribute,
    LoadOrderStatus,
    LotStatus,
    ProductionPosture,
    QualityState,
    RateZone,
    RunStatus,
    SaleableGrade,
    StuccoQualityFlag,
    StuccoTestResult,
    assert_bundle_geometry,
    assert_calciner_batch,
    assert_market,
    assert_production_run,
    assert_seasonality_index,
    factories,
    fixtures,
    test_users,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStuccoYieldArithmetic:
    """One 100.000-ton feed at 10.00 percent moisture on a 90.0 percent pure lot,
    where the conversion factor may only touch the gypsum fraction."""

    def test_the_conversion_factor_applies_only_to_the_gypsum_fraction(
        self, api: ApiClient
    ) -> None:
        """81.000 tons convert at 0.8437 and 9.000 tons of inert pass through at 1.0.

        PRD: "For each feed, the dry tonnage is `tons_fed` multiplied by one minus the chosen moisture basis divided by 100; the gypsum portion of that dry tonnage is the dry tonnage multiplied by that feed's `assay_purity_pct` divided by 100; the inert portion is the dry tonnage minus the gypsum portion; and the feed's contribution is the gypsum portion multiplied by the dihydrate-to-hemihydrate conversion factor of 0.8437 plus the inert portion multiplied by a pass-through factor of 1.0 — inerts survive calcination unchanged."

        Design: Corner/calculations/planned_yield_applies_hemihydrate_factor_only_to_the_gypsum_fraction
        """
        world = fixtures.compact_batch_world(api, close=False)

        closed = validate_success(
            api.close_feed(world.batch_id, {}, test_users.MATERIALS_CONTROLLER), 200
        )

        assert_calciner_batch(closed)
        assert closed["feed_tons_total"] == pytest.approx(100.000, abs=0.0005)
        assert closed["feed_moisture_plan_pct"] == pytest.approx(10.00, abs=0.005)
        assert closed["feed_purity_plan_pct"] == pytest.approx(90.00, abs=0.005)
        assert closed["stucco_yield_plan_tons"] == pytest.approx(77.340, abs=0.0005), (
            "81.000 tons of gypsum at 0.8437 is 68.3397, plus 9.000 tons of inert"
        )
        assert closed["status"] == BatchStatus.CALCINING.value
        assert closed["stucco_yield_actual_tons"] == pytest.approx(0.000, abs=0.0005), (
            "nothing is credited until the batch completes"
        )
        assert world.read_plant()["stucco_on_hand_tons"] == pytest.approx(0.000, abs=0.0005)


class TestProcessEnvelopeFormulas:
    """The tension requirement shares its pivot speed and slope across SKUs and takes
    only its floor from the SKU."""

    def test_required_tension_takes_the_shared_slope_and_the_per_sku_floor(
        self, api: ApiClient
    ) -> None:
        """The REGULAR SKU at 400 fpm needs 37.00 lb; the TYPE_X SKU at 380 fpm needs 39.80.

        PRD: "The system computes `required_paper_tension_lb` as the SKU's `paper_tension_min_lb` plus the quantity of `line_speed_fpm` less 250 multiplied by 0.06, with the result rounded half-up to two decimals — 250 feet per minute is the base speed at which the SKU's stated minimum applies, and each additional foot per minute adds six hundredths of a pound."

        Design: Corner/calculations/required_paper_tension_scales_with_line_speed_above_the_pivot
        """
        world = fixtures.baseline(api)
        batch = fixtures.create_batch(api, world.plant_id)

        regular = validate_success(
            api.create_production_run(
                factories.run_draft_payload(
                    world.plant_id,
                    world.line_id,
                    world.spec_reg["id"],
                    batch["id"],
                    requested_planned_msf=100.0,
                    line_speed_fpm=400,
                    paper_tension_lb=38.0,
                    kiln_dwell_minutes=40,
                ),
                test_users.PRODUCTION_SCHEDULER,
            ),
            201,
        )
        type_x = validate_success(
            api.create_production_run(
                factories.run_draft_payload(
                    world.plant_id,
                    world.line_id,
                    world.spec_tx["id"],
                    batch["id"],
                    window_start="2026-08-04T06:00:00Z",
                    window_end="2026-08-04T10:00:00Z",
                    requested_planned_msf=100.0,
                    line_speed_fpm=380,
                    paper_tension_lb=40.0,
                    kiln_dwell_minutes=50,
                ),
                test_users.PRODUCTION_SCHEDULER,
            ),
            201,
        )

        for run in (regular, type_x):
            assert_production_run(run)
            assert run["status"] == RunStatus.DRAFT.value

        assert regular["required_paper_tension_lb"] == pytest.approx(37.00, abs=0.005), (
            "28.0 plus 150 feet a minute above the pivot at six hundredths each"
        )
        assert type_x["required_paper_tension_lb"] == pytest.approx(39.80, abs=0.005), (
            "32.0 plus 130 feet a minute above the pivot at six hundredths each"
        )
        assert regular["paper_tension_lb"] == pytest.approx(38.0, abs=0.005)
        assert type_x["paper_tension_lb"] == pytest.approx(40.0, abs=0.005), (
            "both chosen tensions sit inside their SKU's window, so neither draft was refused"
        )


class TestBundleAndFreightPrecision:
    """Three bundle quantities rounded at six, four and three decimals, and the six
    markets that pin the three freight zone cut points."""

    def test_bundle_metrics_round_at_six_four_and_three_decimals(
        self, api: ApiClient
    ) -> None:
        """48 boards of 4 by 12 feet give 0.048000, 2.3040 and 11.520 with 18432.00 pounds.

        PRD: "`board_msf_each` is `board_length_ft` multiplied by `board_width_in`, divided by 12 to bring width into feet, then divided by 1000 to express the area in thousands of square feet, rounded half-up to six decimals."

        Design: Corner/calculations/bundle_metrics_hold_six_four_and_three_decimal_precision
        """
        world = fixtures.released_run_with_load(api, bundles_count=5)

        load = world.read_load()
        assert load["status"] == LoadOrderStatus.STAGED.value
        assert load["board_msf_each"] == pytest.approx(0.048000, abs=0.0000005)
        assert load["bundle_msf"] == pytest.approx(2.3040, abs=0.00005)
        assert load["bundle_weight_lb"] == pytest.approx(3686.40, abs=0.005), (
            "48 boards at 1600.0 pounds a MSF over 0.048000 MSF each"
        )
        assert load["total_msf"] == pytest.approx(11.520, abs=0.0005)
        assert load["trailer_weight_lb"] == pytest.approx(18432.00, abs=0.005)
        assert_bundle_geometry(load)
        assert load["loaded_bundles_count"] is None
        assert load["settled_freight_usd"] is None
        assert load["freight_variance_usd"] is None

        assert world.read_run()["available_msf"] == pytest.approx(278.480, abs=0.0005), (
            "290.000 net good less the 11.520 this order committed"
        )

    def test_the_zone_cut_points_are_inclusive_below_and_exclusive_above(
        self, api: ApiClient
    ) -> None:
        """149/150, 349/350 and 599/600 split the four zones one mile apart.

        PRD: "Each zone boundary is inclusive at its lower edge and exclusive at its upper edge, so a market exactly 350 miles out is `ZONE_3`."

        Design: Corner/calculations/freight_zone_boundaries_fall_at_150_350_and_600_miles
        """
        expected = (
            (149, RateZone.ZONE_1.value, 8.50),
            (150, RateZone.ZONE_2.value, 12.75),
            (349, RateZone.ZONE_2.value, 12.75),
            (350, RateZone.ZONE_3.value, 17.40),
            (599, RateZone.ZONE_3.value, 17.40),
            (600, RateZone.ZONE_4.value, 23.10),
        )

        for miles, zone, rate in expected:
            market = validate_success(
                api.create_market(
                    factories.market_payload(
                        name=f"M{miles}",
                        distance_miles=miles,
                        fuel_surcharge_pct=10.0,
                        min_charge_usd=100.0,
                        backhaul_credit_usd=0.0,
                    ),
                    test_users.PLANT_ADMIN,
                ),
                201,
            )
            assert_market(market)
            assert market["rate_zone"] == zone, f"{miles} miles must fall in {zone}"
            assert market["base_rate_per_msf"] == pytest.approx(rate, abs=0.005)


class TestCalcinerCapacityInputSet:
    """The aggregate rate check reads only the three live batch statuses, so windows
    over a COMPLETED or an ABORTED batch are free."""

    @staticmethod
    def _plant_with_one_completed_and_one_aborted_batch(api: ApiClient):
        """B1 completed over 08:00-14:00 at 40.0 tph and B3 aborted over 16:00-20:00."""
        world = fixtures.baseline_with_lots(api)
        batch_1 = fixtures.create_batch(api, world.plant_id)
        fixtures.feed(api, batch_1["id"], world.lot_a_id, 100.0, 9.4)
        fixtures.close_feed(api, batch_1["id"])
        fixtures.record_stucco_test(api, batch_1["id"])
        batch_3 = fixtures.create_batch(
            api,
            world.plant_id,
            target_stucco_tons=40.0,
            feed_rate_tph=40.0,
            feed_window_start="2026-08-02T16:00:00Z",
            feed_window_end="2026-08-02T20:00:00Z",
        )
        fixtures.abort_batch(api, batch_3["id"])
        return world, batch_1["id"], batch_3["id"]

    def test_windows_over_released_batches_are_free_while_live_ones_still_collide(
        self, api: ApiClient
    ) -> None:
        """40.0 tph over a COMPLETED batch is accepted; 40.0 over a live 40.0 is not.

        PRD: "To test a proposed batch, the system gathers every sibling batch at the same plant whose `status` is `PLANNED`, `FEEDING` or `CALCINING`; batches that have reached `COMPLETED` or `ABORTED` have released their window and are ignored."

        Design: Corner/calculations/calciner_capacity_ignores_completed_and_aborted_batches
        """
        world, batch_1_id, batch_3_id = self._plant_with_one_completed_and_one_aborted_batch(api)
        assert fixtures.read_batch(api, batch_1_id)["status"] == BatchStatus.COMPLETED.value
        assert fixtures.read_batch(api, batch_3_id)["status"] == BatchStatus.ABORTED.value

        over_completed = validate_success(
            api.create_calciner_batch(
                factories.calciner_batch_payload(
                    world.plant_id,
                    target_stucco_tons=80.0,
                    feed_rate_tph=40.0,
                    feed_window_start="2026-08-02T10:00:00Z",
                    feed_window_end="2026-08-02T14:00:00Z",
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            201,
        )
        assert over_completed["status"] == BatchStatus.PLANNED.value, (
            "the window lies wholly inside the completed batch's window"
        )

        over_aborted = validate_success(
            api.create_calciner_batch(
                factories.calciner_batch_payload(
                    world.plant_id,
                    target_stucco_tons=40.0,
                    feed_rate_tph=20.0,
                    feed_window_start="2026-08-02T17:00:00Z",
                    feed_window_end="2026-08-02T19:00:00Z",
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            201,
        )
        assert over_aborted["status"] == BatchStatus.PLANNED.value

        validate_error(
            api.create_calciner_batch(
                factories.calciner_batch_payload(
                    world.plant_id,
                    target_stucco_tons=80.0,
                    feed_rate_tph=40.0,
                    feed_window_start="2026-08-02T12:00:00Z",
                    feed_window_end="2026-08-02T16:00:00Z",
                ),
                test_users.MATERIALS_CONTROLLER,
            ),
            ApiErrorId.CALCINER_CAPACITY_EXCEEDED.value,
            409,
        )

        _, meta = validate_paginated(
            api.list_calciner_batches(
                test_users.MATERIALS_CONTROLLER, params={"plant_id": world.plant_id}
            )
        )
        assert meta["total_count"] == 4, "the refused plan created no batch"


class TestStuccoSampleBands:
    """0.30 percent free water is a clean PASS and 0.40 is MARGINAL, and both credit
    the silo identically."""

    @staticmethod
    def _two_closed_batches_on_one_two_hundred_ton_lot(api: ApiClient):
        """BM and B2 each fed 100.000 tons of the same 10.00 / 90.0 lot, both closed."""
        world = fixtures.compact_batch_world(api, received_tons=200.0)
        batch_2 = fixtures.create_batch(
            api,
            world.plant_id,
            target_stucco_tons=80.0,
            feed_rate_tph=25.0,
            feed_window_start="2026-08-02T12:00:00Z",
            feed_window_end="2026-08-02T16:00:00Z",
        )
        fixtures.feed(api, batch_2["id"], world.lot_a_id, 100.0, 10.0)
        world.batch_2 = fixtures.close_feed(api, batch_2["id"])
        return world

    def test_the_pass_ceiling_and_the_marginal_band_both_complete_the_batch(
        self, api: ApiClient
    ) -> None:
        """Only the flag differs: 77.340 tons reach the silo from each batch.

        PRD: "Only if all three fail-band tests are survived does the fourth test run: if `free_water_pct` is above 0.30, or `set_time_minutes` is below 4.00, or `set_time_minutes` is above 12.00, the result is `MARGINAL`."

        Design: Corner/calculations/free_water_at_pass_ceiling_versus_marginal_band
        """
        world = self._two_closed_batches_on_one_two_hundred_ton_lot(api)

        passing = fixtures.record_stucco_test(api, world.batch_id, free_water_pct=0.3)
        marginal = fixtures.record_stucco_test(api, world.batch_2["id"], free_water_pct=0.4)

        assert passing["result"] == StuccoTestResult.PASS.value, "0.30 sits on the inclusive ceiling"
        assert marginal["result"] == StuccoTestResult.MARGINAL.value

        first = world.read_batch()
        assert first["status"] == BatchStatus.COMPLETED.value
        assert first["stucco_quality_flag"] == StuccoQualityFlag.PASS.value
        assert first["stucco_yield_actual_tons"] == pytest.approx(77.340, abs=0.0005)

        second = world.read_batch(world.batch_2["id"])
        assert second["status"] == BatchStatus.COMPLETED.value
        assert second["stucco_quality_flag"] == StuccoQualityFlag.MARGINAL.value
        assert second["stucco_yield_actual_tons"] == pytest.approx(77.340, abs=0.0005)

        plant = world.read_plant()
        assert plant["stucco_on_hand_tons"] == pytest.approx(154.680, abs=0.0005)
        assert plant["stucco_available_tons"] == pytest.approx(154.680, abs=0.0005)
        assert plant["production_posture"] == ProductionPosture.OPEN.value


class TestFeedAggregation:
    """`feed_tons_total` is a running sum recomputed on every feed, not only when the
    feed side closes."""

    def test_the_running_total_advances_with_each_feed_and_each_lot_drops_in_step(
        self, api: ApiClient
    ) -> None:
        """120.000, then 200.000, then 260.000, with the planned yield still 0.000.

        PRD: "On the batch side, the first feed drives `PLANNED → FEEDING` and every subsequent feed keeps the batch in `FEEDING`; `feed_tons_total` is recomputed as the sum of `tons_fed` across the batch's feeds to three decimals, both blend metrics are recomputed, and the batch's `version` increments by 1."

        Design: Corner/calculations/feed_totals_accumulate_across_successive_feeds
        """
        world = fixtures.baseline_with_lots(api)
        batch = fixtures.create_batch(api, world.plant_id)

        fixtures.feed(api, batch["id"], world.lot_a_id, 120.0, 10.2)
        after_one = fixtures.read_batch(api, batch["id"])
        assert after_one["status"] == BatchStatus.FEEDING.value
        assert after_one["feed_tons_total"] == pytest.approx(120.000, abs=0.0005)
        assert world.read_lot_a()["remaining_tons"] == pytest.approx(180.000, abs=0.0005)

        fixtures.feed(api, batch["id"], world.lot_b_id, 80.0, 3.1)
        after_two = fixtures.read_batch(api, batch["id"])
        assert after_two["feed_tons_total"] == pytest.approx(200.000, abs=0.0005)
        assert world.read_lot_b()["remaining_tons"] == pytest.approx(120.000, abs=0.0005)

        fixtures.feed(api, batch["id"], world.lot_a_id, 60.0, 9.8)
        after_three = fixtures.read_batch(api, batch["id"])
        assert after_three["feed_tons_total"] == pytest.approx(260.000, abs=0.0005)
        lot_a = world.read_lot_a()
        assert lot_a["consumed_tons"] == pytest.approx(180.000, abs=0.0005)
        assert lot_a["remaining_tons"] == pytest.approx(120.000, abs=0.0005)
        assert lot_a["status"] == LotStatus.APPROVED.value

        _, meta = validate_paginated(
            api.list_batch_feeds(test_users.MATERIALS_CONTROLLER, params={"batch_id": batch["id"]})
        )
        assert meta["total_count"] == 3
        assert after_three["stucco_yield_plan_tons"] == pytest.approx(0.000, abs=0.0005), (
            "the planned yield is stamped only when the feed side closes"
        )


class TestSeasonalityTable:
    """A twelve-entry lookup keyed on the month of `window_start`, stamped at propose
    time whatever the gate would later say."""

    def test_four_months_stamp_their_table_entries_at_propose_time(
        self, api: ApiClient
    ) -> None:
        """January 0.62, April 1.05, July 1.20 and October 0.90 on identical windows.

        PRD: "`seasonality_index` is read from a fixed housing-market table by the calendar month of `window_start` in UTC: January 0.62, February 0.66, March 0.85, April 1.05, May 1.18, June 1.24, July 1.20, August 1.16, September 1.06, October 0.90, November 0.80, December 0.68."

        Design: Corner/calculations/seasonality_index_is_looked_up_per_window_start_month
        """
        world = fixtures.baseline(api)

        windows = (
            ("2027-01-11T06:00:00Z", "2027-01-12T06:00:00Z", "january slot", 0.62),
            ("2027-04-12T06:00:00Z", "2027-04-13T06:00:00Z", "april slot", 1.05),
            ("2027-07-12T06:00:00Z", "2027-07-13T06:00:00Z", "july slot", 1.20),
            ("2027-10-11T06:00:00Z", "2027-10-12T06:00:00Z", "october slot", 0.90),
        )

        for start, end, note, index in windows:
            outage = fixtures.propose_outage(
                api,
                world.line_id,
                window_start=start,
                window_end=end,
                scope_note=note,
            )
            assert outage["status"] == "PROPOSED"
            assert outage["deferral_count"] == 0
            assert outage["seasonality_index"] == pytest.approx(index, abs=0.005), (
                f"{note} must stamp {index}"
            )
            assert_seasonality_index(outage)
            assert outage["planned_downtime_hours"] == pytest.approx(24.00, abs=0.005)
            assert outage["at_risk_msf"] == pytest.approx(0.000, abs=0.0005)
            assert outage["opportunity_cost_usd"] == pytest.approx(0.00, abs=0.005)


class TestFailRateCeiling:
    """One failing specimen in four is exactly 0.2500, which downgrades rather than
    holds and leaves the volume untouched."""

    def test_a_quarter_fail_rate_downgrades_and_keeps_the_whole_volume_saleable(
        self, api: ApiClient
    ) -> None:
        """Three passing specimens and one short nail pull put the run in SECONDS.

        PRD: "Otherwise, if `fail_rate` is less than or equal to 0.2500, the outcome is `DOWNGRADED`; the ceiling is inclusive, so a fail rate of exactly one specimen in four downgrades rather than holds."

        Design: Corner/calculations/fail_rate_exactly_at_the_downgrade_ceiling_downgrades_rather_than_holds
        """
        world = fixtures.completed_run(api)
        fixtures.record_passing_specimens(api, world.run_id, 3)
        failing = fixtures.record_specimen(
            api, world.run_id, factories.NAIL_PULL_FAILING_SPECIMEN
        )

        assert failing["result"] == "FAIL"
        assert failing["failing_attributes"] == [FailingAttribute.NAIL_PULL.value], (
            "the 0.58 exit moisture sits inside the 0.50 target plus 0.10 tolerance"
        )

        evaluated = fixtures.evaluate(api, world.run_id)

        assert evaluated["specimen_count"] == 4
        assert evaluated["failing_specimen_count"] == 1
        assert evaluated["fail_rate"] == pytest.approx(0.2500, abs=0.00005)
        assert evaluated["quality_state"] == QualityState.DOWNGRADED.value
        assert evaluated["saleable_grade"] == SaleableGrade.SECONDS.value
        assert evaluated["net_good_msf"] == pytest.approx(290.000, abs=0.0005)
        assert evaluated["scrapped_msf"] == pytest.approx(0.000, abs=0.0005)
        assert evaluated["available_msf"] == pytest.approx(290.000, abs=0.0005)
        assert evaluated["status"] == RunStatus.COMPLETED.value
        assert evaluated["last_failing_test_recorded_by_user_id"] == test_users.USER_INSPECTOR_1
