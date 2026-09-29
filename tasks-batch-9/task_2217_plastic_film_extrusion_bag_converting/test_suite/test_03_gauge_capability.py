"""Gauge capability: the five-sample threshold and the CAPABLE band edge."""
import pytest

from test_helpers import (
    CLOCK_D2_0600,
    EXTRUDER,
    ApiErrorId,
    add_gauge_readings,
    create_extrusion_run_payload,
    get_success_data,
    set_logical_clock,
    setup_approved_food_recipe,
    setup_approved_non_food_recipe,
    validate_error,
    validate_success,
)


def _schedule(api, world, run_code, start, end, target_output_kg=1000.0):
    return get_success_data(api.create_extrusion_run(
        create_extrusion_run_payload(world["line"]["id"], world["recipe"]["id"],
                                     run_code=run_code,
                                     scheduled_start=start,
                                     scheduled_end=end,
                                     target_output_kg=target_output_kg),
        EXTRUDER))


class TestCapableThresholdBoundary:
    """1.330 is CAPABLE; 1.323 -- one notch of spread wider -- is MARGINAL."""

    @staticmethod
    def _two_gauged_runs(api):
        world = setup_approved_food_recipe(api)
        run_a = _schedule(api, world, "RUN-FD-1",
                          "2026-08-05T06:00:00Z", "2026-08-05T18:00:00Z")
        run_b = _schedule(api, world, "RUN-FD-2",
                          "2026-08-06T06:00:00Z", "2026-08-06T14:00:00Z")

        get_success_data(api.start_extrusion_run(run_a["id"], EXTRUDER))
        add_gauge_readings(api, run_a["id"], (48.77, 51.23, 49.0, 51.0, 50.0))

        set_logical_clock(api, CLOCK_D2_0600)
        get_success_data(api.start_extrusion_run(run_b["id"], EXTRUDER))
        add_gauge_readings(api, run_b["id"], (48.76, 51.24, 49.0, 51.0, 50.0))

        world["run_a"] = get_success_data(api.get_extrusion_run(run_a["id"], EXTRUDER))
        world["run_b"] = get_success_data(api.get_extrusion_run(run_b["id"], EXTRUDER))
        return world

    def test_index_exactly_at_one_three_three_zero_reads_capable(self, api):
        """A population spread of 1.0026 micron lands the index on 1.330.

        PRD: "`gauge_capability_state` is then read **from that rounded value**:
        `CAPABLE` when the index is at least 1.330, `MARGINAL` when it is at
        least 1.000, and `INCAPABLE` otherwise."

        Design: Difficulty/boundary_precision_check/gauge_cpk_at_capable_threshold_versus_one_ten_thousandth_below
        """
        run_a = self._two_gauged_runs(api)["run_a"]

        assert run_a["gauge_sample_count"] == 5
        assert run_a["gauge_mean_micron"] == pytest.approx(50.000, abs=0.01)
        assert run_a["gauge_sd_micron"] == pytest.approx(1.0026, abs=0.01)
        assert run_a["gauge_cv_pct"] == pytest.approx(2.005, abs=0.01)
        assert run_a["gauge_capability_index"] == pytest.approx(1.330, abs=0.01)
        assert run_a["gauge_capability_state"] == "CAPABLE"

    def test_index_one_notch_below_the_threshold_reads_marginal(self, api):
        """Widening the extremes by 0.01 micron drops the index to 1.323.

        PRD: the standard deviation is "the sum
        of squared deviations from the mean divided by the sample count itself"
        rather than by the count less one.

        Design: Difficulty/boundary_precision_check/gauge_cpk_at_capable_threshold_versus_one_ten_thousandth_below
        """
        run_b = self._two_gauged_runs(api)["run_b"]

        assert run_b["gauge_sample_count"] == 5
        assert run_b["gauge_mean_micron"] == pytest.approx(50.000, abs=0.01)
        assert run_b["gauge_sd_micron"] == pytest.approx(1.0075, abs=0.01)
        assert run_b["gauge_cv_pct"] == pytest.approx(2.015, abs=0.01)
        assert run_b["gauge_capability_index"] == pytest.approx(1.323, abs=0.01)
        assert run_b["gauge_capability_state"] == "MARGINAL"

    def test_layflat_and_bubble_readings_stay_at_their_defaults(self, api):
        """Samples logged without optional geometry report no deviation.

        PRD: "`bubble_instability_events` counts the samples whose
        `bubble_deviation_mm` has an absolute value strictly greater than 3.0
        millimetres."

        Design: Difficulty/boundary_precision_check/gauge_cpk_at_capable_threshold_versus_one_ten_thousandth_below
        """
        run_a = self._two_gauged_runs(api)["run_a"]

        assert run_a["layflat_deviation_max_mm"] == pytest.approx(0.0, abs=0.01)
        assert run_a["bubble_instability_events"] == 0


class TestGaugeSampleCountMinimum:
    """Five samples is the floor for both capability and run closure."""

    @staticmethod
    def _four_sample_run(api):
        world = setup_approved_non_food_recipe(api)
        run = _schedule(api, world, "RUN-NF-1",
                        "2026-08-05T06:00:00Z", "2026-08-05T14:00:00Z",
                        target_output_kg=500.0)
        get_success_data(api.start_extrusion_run(run["id"], EXTRUDER))
        add_gauge_readings(api, run["id"], (40.0,) * 4)
        world["run"] = get_success_data(api.get_extrusion_run(run["id"], EXTRUDER))
        return world

    def test_four_samples_leave_the_capability_block_null(self, api):
        """One sample short of the floor, nothing is published.

        PRD: "The capability block behaves in two regimes. While fewer than five
        samples exist, `gauge_mean_micron`, `gauge_sd_micron`, `gauge_cv_pct` and
        `gauge_capability_index` are all null and `gauge_capability_state` reads
        `INSUFFICIENT_DATA`."

        Design: Difficulty/boundary_precision_check/gauge_sample_count_at_minimum_versus_one_below
        """
        run = self._four_sample_run(api)["run"]

        assert run["gauge_sample_count"] == 4
        assert run["gauge_capability_state"] == "INSUFFICIENT_DATA"
        assert run["gauge_capability_index"] is None

    def test_completion_refused_one_sample_short(self, api):
        """Closure demands the same five samples.

        PRD: "It requires at least five gauge samples, or
        `ERR_INSUFFICIENT_GAUGE_DATA`".

        Design: Difficulty/boundary_precision_check/gauge_sample_count_at_minimum_versus_one_below
        """
        world = self._four_sample_run(api)
        validate_error(
            api.complete_extrusion_run(world["run"]["id"], 500.0, 100.0, EXTRUDER),
            ApiErrorId.ERR_INSUFFICIENT_GAUGE_DATA, 422)

        run = get_success_data(api.get_extrusion_run(world["run"]["id"], EXTRUDER))
        assert run["status"] == "RUNNING"
        assert run["gross_output_kg"] is None
        assert run["net_good_kg"] is None

    def test_fifth_sample_unlocks_a_zero_spread_ceiling_index(self, api):
        """Five identical samples give a zero spread and the ceiling index.

        PRD: "When the standard deviation is exactly zero the raw index is taken
        as the ceiling value 4.000."

        Design: Difficulty/boundary_precision_check/gauge_sample_count_at_minimum_versus_one_below
        """
        world = self._four_sample_run(api)
        validate_error(
            api.complete_extrusion_run(world["run"]["id"], 500.0, 100.0, EXTRUDER),
            ApiErrorId.ERR_INSUFFICIENT_GAUGE_DATA, 422)
        add_gauge_readings(api, world["run"]["id"], (40.0,))

        completed = validate_success(
            api.complete_extrusion_run(world["run"]["id"], 500.0, 100.0, EXTRUDER),
            200)
        assert completed["gauge_sample_count"] == 5
        assert completed["gauge_sd_micron"] == pytest.approx(0.0000, abs=0.01)
        assert completed["gauge_capability_index"] == pytest.approx(4.000, abs=0.01)
        assert completed["gauge_capability_state"] == "CAPABLE"
        assert completed["status"] == "COMPLETED"
        assert completed["net_good_kg"] == pytest.approx(400.000, abs=0.01)

    def test_closure_books_the_scrap_into_the_matching_pool(self, api):
        """The fifth sample lets closure run its side effects.

        PRD: "A regrind transaction is booked into the eligible pool with
        `direction` `IN` and `origin_kind` `EXTRUSION_SCRAP`, carrying `kg`
        equal to `scrap_kg`".

        Design: Difficulty/boundary_precision_check/gauge_sample_count_at_minimum_versus_one_below
        """
        world = self._four_sample_run(api)
        validate_error(
            api.complete_extrusion_run(world["run"]["id"], 500.0, 100.0, EXTRUDER),
            ApiErrorId.ERR_INSUFFICIENT_GAUGE_DATA, 422)
        add_gauge_readings(api, world["run"]["id"], (40.0,))
        completed = validate_success(
            api.complete_extrusion_run(world["run"]["id"], 500.0, 100.0, EXTRUDER),
            200)

        assert completed["regrind_actual_pct"] == pytest.approx(0.000, abs=0.01)
        assert completed["actual_recycled_content_pct"] == pytest.approx(0.000,
                                                                        abs=0.01)
        pool = get_success_data(api.get_regrind_pool(world["pool"]["id"], EXTRUDER))
        assert pool["cumulative_in_kg"] == pytest.approx(100.000, abs=0.01)
        assert pool["available_kg"] == pytest.approx(100.000, abs=0.01)
        assert pool["generation_count"] == 1
