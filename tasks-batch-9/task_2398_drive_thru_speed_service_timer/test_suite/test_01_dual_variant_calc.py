"""Two-variant calculations: the same stored rows scored two different ways.

The staffing model is selected by the store's `staffing_basis`, and the
throughput metric chain is selected by the report's `variant`.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.test_users import ADMIN_HEADERS, COACH_HEADERS


# ---------------------------------------------------------------- shared setup
def _dual_parallel_store_with_two_merged_cars(api: DriveThruApiClient):
    """A DUAL_PARALLEL store that has closed two cars inside the trailing window.

    Both cars go through the merge lane, so the second car's
    `served_after_loop_id` records which car it merged behind.
    """
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-A",
        lane_config="DUAL_PARALLEL",
        merge_slots_capacity=2,
        labor_minutes_budget=600,
        staff_name="Dana Ruiz",
        name="Peachtree Dual Parallel",
        staffing_basis="OBSERVED",
    )

    fx.set_clock(api, fx.at(11, 0, 0))
    first = fx.open_loop(api, ctx, lane="LANE_A")
    fx.set_clock(api, fx.at(11, 0, 20))
    fx.greet_loop(api, ctx, first["id"])
    fx.set_clock(api, fx.at(11, 1, 0))
    fx.complete_order(api, ctx, first["id"], order_items_count=3)
    slot_one = fx.award_merge_slot(api, ctx)
    fx.commit_slot(api, ctx, slot_one["id"])
    fx.set_clock(api, fx.at(11, 2, 0))
    fx.arrive_at_window(api, ctx, first["id"])
    fx.set_clock(api, fx.at(11, 4, 10))
    fx.depart_loop(api, ctx, first["id"])

    second = fx.open_loop(api, ctx, lane="LANE_B")
    fx.set_clock(api, fx.at(11, 4, 15))
    fx.greet_loop(api, ctx, second["id"])
    fx.set_clock(api, fx.at(11, 4, 16))
    fx.complete_order(api, ctx, second["id"], order_items_count=2)
    slot_two = fx.award_merge_slot(api, ctx)
    fx.commit_slot(api, ctx, slot_two["id"])
    fx.set_clock(api, fx.at(11, 4, 18))
    fx.arrive_at_window(api, ctx, second["id"])
    fx.set_clock(api, fx.at(11, 4, 20))
    fx.depart_loop(api, ctx, second["id"])

    # A negative weather forecast, in force across the whole lunch period.
    fx.applied_override(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(13, 0, 0),
        projected_cars_delta_pct=-0.50,
        source="WEATHER",
    )
    return ctx, first["id"], second["id"]


class TestStaffingBasisVariants:
    """The two staffing-model variants disagree on identical timer-loop rows."""

    def test_observed_basis_ignores_the_in_force_forecast_override(self, api):
        """PRD §3.2: "Under `OBSERVED`, `cars_per_hour_effective` equals
        `cars_per_hour_observed`, so the tier, the lane bump and therefore
        `required_oot_count` are read off the trailing ten-minute closed-car
        count alone and forecast overrides in force are ignored entirely."

        Design: Difficulty/dual_variant_calc/oot_requirement_variant_divergence_on_staffing_basis
        """
        ctx, _first_id, _second_id = _dual_parallel_store_with_two_merged_cars(api)

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=2,
            cars_per_hour_observed=12.0,
            cars_per_hour_effective=12.0,
            volume_tier="TIER_3",
            required_oot_count=3,
            deployed_oot_count=0,
        )
        assert store["staffing_basis"] == "OBSERVED", store

    def test_forecast_adjusted_basis_lowers_the_tier_and_the_oot_requirement(self, api):
        """PRD §3.2: "Under `FORECAST_ADJUSTED`, `cars_per_hour_effective` is
        first scaled by one plus the in-force override's
        `projected_cars_delta_pct` and re-rounded to one decimal place before
        tier selection, so the very same trailing car count can select a lower
        or higher band, can flip the lane bump across the 12-cars-per-hour
        boundary, and can therefore yield a different `required_oot_count` — and
        a different `service_posture` — from the observed variant."

        Design: Difficulty/dual_variant_calc/oot_requirement_variant_divergence_on_staffing_basis
        """
        ctx, _first_id, _second_id = _dual_parallel_store_with_two_merged_cars(api)

        patched = validate_success(
            api.patch_restaurant(
                ctx.restaurant_id,
                {"staffing_basis": "FORECAST_ADJUSTED"},
                ctx.operator_headers,
            ),
            expected_status=200,
        )
        assert patched["staffing_basis"] == "FORECAST_ADJUSTED", patched

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=2,
            cars_per_hour_observed=12.0,
            cars_per_hour_effective=6.0,
            volume_tier="TIER_2",
            required_oot_count=1,
            deployed_oot_count=0,
            service_posture="SURGE",
        )

    def test_second_merged_car_records_the_car_it_merged_behind(self, api):
        """PRD §3.4: "At the same moment the winning loop's
        `served_after_loop_id` is set to the `timer_loop_id` of whichever slot
        held the greatest `sequence_index` *before* this award, or null if this
        is the store's first award — that self-reference is the re-sequencing
        audit trail showing which car this one merged behind."

        Design: Difficulty/dual_variant_calc/oot_requirement_variant_divergence_on_staffing_basis
        """
        _ctx, first_id, second_id = _dual_parallel_store_with_two_merged_cars(api)

        first = validate_success(api.get_timer_loop(first_id, ADMIN_HEADERS))
        second = validate_success(api.get_timer_loop(second_id, ADMIN_HEADERS))
        assert first["served_after_loop_id"] is None, first
        assert second["served_after_loop_id"] == first_id, second


# ------------------------------------------------------- report variant fixture
def _single_lane_store_with_a_clean_car_and_a_remade_car(api: DriveThruApiClient):
    """One car served cleanly, then a second car with a late size complaint.

    The second car carries an open remake, so the two report variants select
    different input sets over the very same ten-minute window.
    """
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-B",
        labor_minutes_budget=600,
        staff_name="Ivy Chen",
        name="Ponce Single Lane",
    )

    clean = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=fx.at(11, 3, 50),
        order_items_count=3,
    )
    remade = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 3, 50),
        greet_at=fx.at(11, 4, 10),
        order_complete_at=fx.at(11, 5, 0),
        window_arrive_at=fx.at(11, 6, 0),
        depart_at=fx.at(11, 8, 40),
        order_items_count=5,
    )
    incident = fx.log_incident(api, ctx, remade["id"], incident_type="WRONG_SIZE")
    fx.set_clock(api, fx.at(11, 10, 0))
    return ctx, clean["id"], remade["id"], incident["id"]


class TestReportVariants:
    """`PROVISIONAL` and `FINAL` score the same rows differently."""

    def test_provisional_report_excludes_the_loop_with_an_open_remake(self, api):
        """PRD §3.8: "A **`PROVISIONAL`** report's input set is the store's
        timer loops whose `timing_state` is `CLOSED` and whose **`depart_at`**
        falls at or after `window_start_at` and strictly before
        `window_end_at`, *excluding* any loop whose `accuracy_state` is
        `REMAKE_OPEN`."

        Design: Difficulty/dual_variant_calc/report_variant_divergence_provisional_vs_final
        """
        ctx, _clean_id, _remade_id, _incident_id = (
            _single_lane_store_with_a_clean_car_and_a_remade_car(api)
        )

        report = fx.create_report(
            api, ctx, fx.at(11, 0, 0), fx.at(11, 10, 0), variant="PROVISIONAL"
        )
        a.assert_report_metrics(
            report,
            metric_basis="TOTAL",
            cars_served=1,
            cars_per_hour=6.0,
            window_tier="TIER_2",
            avg_metric_seconds=230.0,
            mean_pinned_target_seconds=235,
            target_total_seconds_effective=242,
            attainment_pct=105.22,
            attainment_band="GREEN",
            open_remake_incident_count=1,
            coaching_pool_points=4,
        )

    def test_final_report_includes_the_loop_with_an_open_remake(self, api):
        """PRD §3.8: "A **`FINAL`** report's input set is the store's timer
        loops whose `timing_state` is `CLOSED` or `ABANDONED` and whose
        **`arrive_at`** — arrival, not departure — falls at or after
        `window_start_at` and strictly before `window_end_at`, *including*
        loops whose `accuracy_state` is `REMAKE_OPEN`."

        Design: Difficulty/dual_variant_calc/report_variant_divergence_provisional_vs_final
        """
        ctx, _clean_id, _remade_id, _incident_id = (
            _single_lane_store_with_a_clean_car_and_a_remade_car(api)
        )

        report = fx.create_report(
            api, ctx, fx.at(11, 0, 0), fx.at(11, 10, 0), variant="FINAL"
        )
        a.assert_report_metrics(
            report,
            metric_basis="ADJUSTED_TOTAL",
            cars_served=2,
            cars_per_hour=12.0,
            window_tier="TIER_3",
            avg_metric_seconds=270.0,
            mean_pinned_target_seconds=238.5,
            target_total_seconds_effective=255,
            attainment_pct=94.44,
            attainment_band="AMBER",
            coaching_pool_points=1,
        )

    def test_the_two_variants_diverge_on_identical_stored_rows(self, api):
        """PRD §3.8: "Its metric per loop is `adjusted_total_seconds`, with the
        accuracy and escalation penalties folded in, and each `ABANDONED` loop
        in the set contributes a flat 300 seconds as its metric instead. On
        identical stored rows this yields a different `cars_served`, a
        different `window_tier` and a different `attainment_band` from the
        provisional variant."

        Design: Difficulty/dual_variant_calc/report_variant_divergence_provisional_vs_final
        """
        ctx, clean_id, remade_id, incident_id = (
            _single_lane_store_with_a_clean_car_and_a_remade_car(api)
        )

        provisional = fx.create_report(
            api, ctx, fx.at(11, 0, 0), fx.at(11, 10, 0), variant="PROVISIONAL"
        )
        final = fx.create_report(
            api, ctx, fx.at(11, 0, 0), fx.at(11, 10, 0), variant="FINAL"
        )

        # The stored rows the two reports read are one and the same.
        clean = validate_success(api.get_timer_loop(clean_id, COACH_HEADERS))
        remade = validate_success(api.get_timer_loop(remade_id, COACH_HEADERS))
        a.assert_loop_segments(clean, total_seconds=230)
        a.assert_pinned_targets(clean, 25, 95, 40, 75, total=235)
        a.assert_loop_states(clean, accuracy_state="VERIFIED")
        a.assert_loop_segments(remade, total_seconds=290, adjusted_total_seconds=310)
        assert remade["target_total_seconds_pinned"] == 242, remade
        a.assert_loop_states(remade, accuracy_state="REMAKE_OPEN")

        incident = validate_success(api.get_accuracy_incident(incident_id, COACH_HEADERS))
        assert incident["severity"] == "MINOR", incident
        assert incident["penalty_seconds"] == 20, incident
        assert incident["remake_cost_cents"] == 350, incident

        assert (provisional["cars_served"], final["cars_served"]) == (1, 2)
        assert (provisional["window_tier"], final["window_tier"]) == ("TIER_2", "TIER_3")
        assert (provisional["attainment_band"], final["attainment_band"]) == (
            "GREEN",
            "AMBER",
        )
        assert (
            provisional["coaching_pool_points"],
            final["coaching_pool_points"],
        ) == (4, 1)
