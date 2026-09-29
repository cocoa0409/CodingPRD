"""Lane occupancy and the four-hop road-test failure cascade of PRD 3.6."""

import test_helpers as H
from test_helpers import (
    PLANT_ENGINEER,
    QUALITY_INSPECTOR,
    SALES_ADMIN,
    validate_error,
    validate_success,
)


JIG_WINDOWS = (
    ("2026-08-03T09:00:00Z", "2026-08-03T11:00:00Z"),
    ("2026-08-03T12:00:00Z", "2026-08-03T14:00:00Z"),
    ("2026-08-03T15:00:00Z", "2026-08-03T17:00:00Z"),
)


class TestLaneAggregateCapacity:
    def test_a_window_touching_both_scheduled_tests_breaches_a_capacity_of_two(self, api):
        """Touching endpoints count as overlap, so the third booking is refused.

        PRD 3.6: "Because both comparisons are inclusive, two windows that merely
        touch — one ending at the exact instant the next begins — do count as
        overlapping."

        Design: Difficulty/resource_temporal_overlap/lane_closed_intervals_with_aggregate_capacity_of_two
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        first = H.unit_at_systems_installed(plant, api, "SN-000101", JIG_WINDOWS[0])
        second = H.unit_at_systems_installed(plant, api, "SN-000102", JIG_WINDOWS[1])
        third = H.unit_at_systems_installed(plant, api, "SN-000103", JIG_WINDOWS[2])
        H.book_road_test(api, first["unit"]["id"], plant["lane"]["id"], window=H.LANE_WINDOW_1)
        H.book_road_test(api, second["unit"]["id"], plant["lane"]["id"], window=H.LANE_WINDOW_2)

        response = api.book_road_test(
            third["unit"]["id"],
            H.road_test_payload(
                plant["lane"]["id"],
                window=("2026-08-04T11:00:00Z", "2026-08-04T12:00:00Z"),
            ),
            headers=QUALITY_INSPECTOR,
        )

        validate_error(response, H.ERR_LANE_CAPACITY_EXCEEDED)
        assert (
            H.read_unit(api, third["unit"]["id"])["build_status"]
            == H.BuildStatus.SYSTEMS_INSTALLED
        )

    def test_a_window_one_second_inside_the_gap_books_the_third_test(self, api):
        """11:00:01 to 11:59:59 touches neither neighbour and is accepted.

        PRD 3.6: "If the overlapping count is already at or above the lane's
        `max_concurrent_tests`, the booking is refused with
        `ERR_LANE_CAPACITY_EXCEEDED`; with the default capacity of 2, two
        overlapping scheduled tests are fine and a third is not."

        Design: Difficulty/resource_temporal_overlap/lane_closed_intervals_with_aggregate_capacity_of_two
        """
        H.set_clock(api, H.CLOCK_DEFAULT_UTC)
        plant = H.setup_plant(api)
        first = H.unit_at_systems_installed(plant, api, "SN-000101", JIG_WINDOWS[0])
        second = H.unit_at_systems_installed(plant, api, "SN-000102", JIG_WINDOWS[1])
        third = H.unit_at_systems_installed(plant, api, "SN-000103", JIG_WINDOWS[2])
        rt1 = H.book_road_test(
            api, first["unit"]["id"], plant["lane"]["id"], window=H.LANE_WINDOW_1
        )
        rt2 = H.book_road_test(
            api, second["unit"]["id"], plant["lane"]["id"], window=H.LANE_WINDOW_2
        )

        response = api.book_road_test(
            third["unit"]["id"],
            H.road_test_payload(
                plant["lane"]["id"],
                window=("2026-08-04T11:00:01Z", "2026-08-04T11:59:59Z"),
            ),
            headers=QUALITY_INSPECTOR,
        )

        rt3 = validate_success(response, expected_status=201)
        assert rt3["status"] == H.RoadTestStatus.SCHEDULED
        assert rt3["lane_id"] == plant["lane"]["id"]
        assert rt3["protocol_code"] == "STANDARD_20MI"
        assert (
            H.read_unit(api, third["unit"]["id"])["build_status"]
            == H.BuildStatus.ROAD_TEST_PENDING
        )
        assert H.read_road_test(api, rt1["id"])["status"] == H.RoadTestStatus.SCHEDULED
        assert H.read_road_test(api, rt2["id"])["status"] == H.RoadTestStatus.SCHEDULED
        scheduled, meta = H.validate_paginated(
            api.list_lane_road_tests(
                plant["lane"]["id"], params={"status": "SCHEDULED"}, headers=PLANT_ENGINEER
            )
        )
        assert len(scheduled) == 3
        assert meta["total_count"] == 3


def _allocated_trailer_ready_for_a_retest(api):
    """A labelled, stocked and allocated trailer, with its order drawn."""
    H.set_clock(api, H.CLOCK_DEFAULT_UTC)
    plant = H.setup_plant(api)
    staged = H.order_allocated(plant, api)
    labels, _meta = H.validate_paginated(
        api.list_labels(staged["unit"]["id"], headers=SALES_ADMIN)
    )
    staged["label"] = labels[0]
    return plant, staged


class TestRoadTestFailureCascade:
    def test_a_failed_retest_unwinds_the_trailer_and_voids_its_label(self, api):
        """The trailer drops to SYSTEMS_REWORK and NON_COMPLIANT and loses its VIN.

        PRD 3.6: "Hop one: because the trailer left the tested state, its
        certification label whose `status` is `ISSUED`, if it has one, moves
        `ISSUED` → `VOIDED` with `voided_reason` recorded as `ROAD_TEST_FAILED`,
        and the trailer's `vin` becomes null."

        Design: Difficulty/transitive_cascade/road_test_failure_cascades_to_label_order_and_dealer
        """
        plant, staged = _allocated_trailer_ready_for_a_retest(api)
        retest = H.book_road_test(
            api,
            staged["unit"]["id"],
            plant["lane"]["id"],
            window=("2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z"),
        )

        resulted = H.record_road_test_result(
            api,
            retest["id"],
            brake_stop_distance_ft=52.0,
            lighting_check_passed=True,
            result_notes="stop distance out of spec",
        )

        assert resulted["status"] == H.RoadTestStatus.FAILED
        unit = H.read_unit(api, staged["unit"]["id"])
        H.assert_unit_dimensions(
            unit, H.BuildStatus.SYSTEMS_REWORK, H.ComplianceStatus.NON_COMPLIANT
        )
        assert unit["vin"] is None
        assert unit["dealer_order_id"] is None
        labels, _meta = H.validate_paginated(
            api.list_labels(
                staged["unit"]["id"], params={"include_voided": "true"}, headers=SALES_ADMIN
            )
        )
        assert len(labels) == 1
        assert labels[0]["status"] == H.LabelStatus.VOIDED
        assert labels[0]["voided_reason"] == H.VOIDED_REASON_ROAD_TEST_FAILED

    def test_the_voided_label_keeps_its_sequence_number_out_of_the_pool(self, api):
        """A void does not return the minted number to the counter.

        PRD 3.7: "A number is never reused — voiding a label does not return its
        number to the pool — so the sequence is a permanent, gap-free record of
        how many labels the plant has ever minted, and gaps in the set of
        *live* VINs are expected wherever a void has occurred."

        Design: Difficulty/transitive_cascade/road_test_failure_cascades_to_label_order_and_dealer
        """
        plant, staged = _allocated_trailer_ready_for_a_retest(api)
        retest = H.book_road_test(
            api,
            staged["unit"]["id"],
            plant["lane"]["id"],
            window=("2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z"),
        )

        H.record_road_test_result(
            api, retest["id"], brake_stop_distance_ft=52.0, lighting_check_passed=True
        )

        labels, _meta = H.validate_paginated(
            api.list_labels(
                staged["unit"]["id"], params={"include_voided": "true"}, headers=SALES_ADMIN
            )
        )
        assert labels[0]["vin_sequence"] == 1

    def test_the_failure_reaches_the_dealer_order_and_the_credit_line(self, api):
        """The order returns to PENDING and the draw leaves the conserved sum.

        PRD 3.6: "Hop three: because the draw was released, the dealer's
        `floor_plan_outstanding_cents` is reduced by that order's
        `floor_plan_draw_cents`, `floor_plan_available_cents` is recomputed, and
        the dealer's `version` increments."

        Design: Difficulty/transitive_cascade/road_test_failure_cascades_to_label_order_and_dealer
        """
        plant, staged = _allocated_trailer_ready_for_a_retest(api)
        retest = H.book_road_test(
            api,
            staged["unit"]["id"],
            plant["lane"]["id"],
            window=("2026-08-06T10:00:00Z", "2026-08-06T11:00:00Z"),
        )

        H.record_road_test_result(
            api, retest["id"], brake_stop_distance_ft=52.0, lighting_check_passed=True
        )

        order = H.read_order(api, staged["order"]["id"])
        assert order["status"] == H.OrderStatus.PENDING
        assert order["allocated_unit_id"] is None
        assert order["floor_plan_status"] == H.FloorPlanStatus.RELEASED
        # The draw is retained on the row for audit even though it has left the sum.
        H.assert_money(order["floor_plan_draw_cents"], H.ORDER1_DRAW_CENTS)
        dealer = H.read_dealer(api, plant["dealer"]["id"])
        H.assert_floor_plan_conserved(dealer, 0)
        H.assert_money(dealer["floor_plan_available_cents"], H.DEALER_FLOOR_PLAN_LIMIT_CENTS)
        assert dealer["allocations_current_month_count"] == 0
