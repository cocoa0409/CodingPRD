"""Values landing exactly on a boundary, where inclusivity decides the answer.

Three different metrics on three different endpoints: a car rate on a band edge
at departure, a zero-car window at publish, and a greet measured exactly on its
pinned target at greet.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import ERR_REPORT_WINDOW_EMPTY
from test_helpers.test_users import ADMIN_HEADERS, COACH_HEADERS


# ------------------------------------------------- car rate exactly on a band edge
def _one_departed_car_and_a_second_at_the_window(api: DriveThruApiClient):
    """Two cars, the first already closed and the second waiting to depart."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-N",
        staff_name="Omar Reyes",
        name="Dunwoody Single Lane",
    )
    first = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=None,
        order_items_count=3,
    )
    second = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 2, 10),
        greet_at=fx.at(11, 2, 30),
        order_complete_at=fx.at(11, 3, 0),
        window_arrive_at=fx.at(11, 3, 20),
        depart_at=None,
        order_items_count=2,
    )
    fx.set_clock(api, fx.at(11, 4, 10))
    fx.depart_loop(api, ctx, first["id"])
    fx.set_clock(api, fx.at(11, 4, 20))
    return ctx, first["id"], second["id"], second["target_total_seconds_pinned"]


class TestTierFloorIsInclusive:
    """Twelve cars per hour belongs to the band whose floor is 12."""

    def test_one_car_sits_below_the_edge_in_the_lower_band(self, api):
        """PRD §2.4: "`volume_tier` is the `tier` of the volume-tier band whose
        `cars_per_hour_floor` is less than or equal to `cars_per_hour_effective`
        and whose `cars_per_hour_ceiling` is either null or strictly greater than
        `cars_per_hour_effective`."

        Design: Difficulty/boundary_precision_check/tier_floor_exact_inclusive_on_depart
        """
        ctx, _first_id, _second_id, pinned = (
            _one_departed_car_and_a_second_at_the_window(api)
        )

        # The second car pinned while the store was still quiet, so relief was 0.00.
        assert pinned == 235, pinned
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=1,
            cars_per_hour_effective=6.0,
            volume_tier="TIER_2",
        )

    def test_the_second_departure_lands_on_the_edge_and_takes_the_upper_band(
        self, api
    ):
        """PRD §2.4: "`cars_per_hour_observed` is `cars_closed_trailing` multiplied
        by 3600 and divided by the 600-second trailing window length, rounded
        half up to one decimal place."

        Design: Difficulty/boundary_precision_check/tier_floor_exact_inclusive_on_depart
        """
        ctx, _first_id, second_id, _pinned = (
            _one_departed_car_and_a_second_at_the_window(api)
        )

        fx.depart_loop(api, ctx, second_id)

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=2,
            cars_per_hour_observed=12.0,
            cars_per_hour_effective=12.0,
            volume_tier="TIER_3",
            required_oot_count=2,
            deployed_oot_count=0,
            service_posture="SURGE",
        )
        # 12.0 is not strictly below the lower band's ceiling of 12.
        assert store["volume_tier"] != "TIER_2", store

    def test_the_second_cars_own_segments_are_all_inside_target(self, api):
        """PRD §3.3: "`breach_flags` is the subset of `[GREET, ORDER,
        PULL_FORWARD, WINDOW]` — always reported in exactly that order — whose
        measured seconds are *strictly greater* than the corresponding pinned
        target"

        Design: Difficulty/boundary_precision_check/tier_floor_exact_inclusive_on_depart
        """
        ctx, _first_id, second_id, _pinned = (
            _one_departed_car_and_a_second_at_the_window(api)
        )

        departed = fx.depart_loop(api, ctx, second_id)
        a.assert_loop_segments(
            departed,
            greet_seconds=20,
            order_seconds=30,
            pull_forward_seconds=20,
            window_seconds=60,
            total_seconds=130,
        )
        a.assert_breach_flags(departed, [])


# ------------------------------------------------------- zero cars in the window
def _quiet_store_with_no_cars_at_all(api: DriveThruApiClient):
    """A store that opened, served nobody, and has reached 11:05."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-O",
        staff_name="Pia Nwosu",
        name="Alpharetta Quiet Hour",
    )
    fx.set_clock(api, fx.at(11, 5, 0))
    return ctx


class TestEmptyWindowReport:
    """A window with no cars is reportable but not publishable."""

    def test_an_empty_window_report_is_created_with_null_metrics(self, api):
        """PRD §3.8: "An empty window is handled explicitly rather than by
        division: when `cars_served` is 0, `avg_metric_seconds`,
        `mean_pinned_target_seconds`, `target_total_seconds_effective`,
        `attainment_pct` and `attainment_band` are all null, `cars_per_hour` is
        0.0, `window_tier` is the tier of the band containing a car rate of 0.0,
        and `coaching_pool_points` is 0."

        Design: Difficulty/boundary_precision_check/report_publish_rejects_zero_car_window
        """
        ctx = _quiet_store_with_no_cars_at_all(api)

        report = validate_success(
            api.create_throughput_report(
                {
                    "restaurant_id": ctx.restaurant_id,
                    "window_start_at": fx.at(11, 0, 0),
                    "window_end_at": fx.at(11, 5, 0),
                    "variant": "PROVISIONAL",
                    "expected_restaurant_version": fx.current_restaurant_version(
                        api, ctx.restaurant_id
                    ),
                },
                COACH_HEADERS,
            ),
            expected_status=201,
        )
        a.assert_empty_window_report(report)
        a.assert_report_metrics(
            report, window_tier="TIER_1", open_remake_incident_count=0
        )

    def test_publishing_an_empty_window_is_rejected(self, api):
        """PRD §3.8: "Such a report may be created — it is a legitimate statement
        that nothing happened — but it may not be published, and the publish
        attempt is rejected with `ERR_REPORT_WINDOW_EMPTY`."

        Design: Difficulty/boundary_precision_check/report_publish_rejects_zero_car_window
        """
        ctx = _quiet_store_with_no_cars_at_all(api)

        report = fx.create_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
        validate_error(
            api.publish_throughput_report(report["id"], COACH_HEADERS),
            ERR_REPORT_WINDOW_EMPTY,
        )

    def test_the_rejected_publish_leaves_the_report_in_draft(self, api):
        """PRD §2.11: "**Non-empty report** — the report being published has a
        `cars_served` of at least 1."

        Design: Difficulty/boundary_precision_check/report_publish_rejects_zero_car_window
        """
        ctx = _quiet_store_with_no_cars_at_all(api)

        report = fx.create_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
        assert report["report_state"] == "DRAFT", report

        validate_error(
            api.publish_throughput_report(report["id"], COACH_HEADERS),
            ERR_REPORT_WINDOW_EMPTY,
        )

        after = validate_success(
            api.get_throughput_report(report["id"], COACH_HEADERS)
        )
        assert after["report_state"] == "DRAFT", after
        assert after["cars_served"] == 0, after


# ------------------------------------------- greet measured exactly on its target
def _car_greeted_exactly_on_target(api: DriveThruApiClient):
    """A car whose greet lands on the pinned 25-second mark to the second."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-P",
        staff_name="Gus Kaplan",
        name="Smyrna Single Lane",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    loop = fx.open_loop(api, ctx)
    fx.set_clock(api, fx.at(11, 0, 25))
    return ctx, loop["id"], loop["greet_target_pinned"]


class TestGreetEqualToTargetIsNotABreach:
    """Equality is not a breach, because the comparison is strictly greater-than."""

    def test_a_greet_equal_to_the_pinned_target_raises_no_flag(self, api):
        """PRD §3.3: "`breach_flags` is the subset of `[GREET, ORDER,
        PULL_FORWARD, WINDOW]` — always reported in exactly that order — whose
        measured seconds are *strictly greater* than the corresponding pinned
        target"

        Design: Difficulty/boundary_precision_check/greet_equal_to_pinned_target_is_not_a_breach
        """
        ctx, loop_id, pinned_greet = _car_greeted_exactly_on_target(api)

        assert pinned_greet == 25, pinned_greet

        greeted = fx.greet_loop(api, ctx, loop_id)
        assert greeted["greet_seconds"] == 25, greeted
        assert greeted["greet_target_pinned"] == 25, greeted
        a.assert_breach_flags(greeted, [])
        assert "GREET" not in greeted["breach_flags"], greeted

    def test_greeting_stamps_the_clock_and_leaves_the_later_segments_null(self, api):
        """PRD §3.3: "Greeting a car moves it `OPEN → GREETED`, stamping `greet_at`
        and computing `greet_seconds` as `greet_at` minus `arrive_at` in whole
        seconds."

        Design: Difficulty/boundary_precision_check/greet_equal_to_pinned_target_is_not_a_breach
        """
        ctx, loop_id, _pinned_greet = _car_greeted_exactly_on_target(api)

        greeted = fx.greet_loop(api, ctx, loop_id)
        a.assert_loop_states(greeted, timing_state="GREETED")
        assert greeted["greet_at"] == fx.at(11, 0, 25), greeted
        a.assert_all_null(greeted, ["order_seconds", "total_seconds"])

    def test_the_pinned_target_total_is_the_unrelieved_profile_sum(self, api):
        """PRD §3.3: "The **override relief** is 0.00 when no forecast override is
        in force at the current clock reading"

        Design: Difficulty/boundary_precision_check/greet_equal_to_pinned_target_is_not_a_breach
        """
        ctx, loop_id, _pinned_greet = _car_greeted_exactly_on_target(api)

        greeted = fx.greet_loop(api, ctx, loop_id)
        a.assert_pinned_targets(greeted, 25, 95, 40, 75, total=235)

        stored = validate_success(api.get_timer_loop(loop_id, ADMIN_HEADERS))
        assert stored["target_total_seconds_pinned"] == 235, stored
