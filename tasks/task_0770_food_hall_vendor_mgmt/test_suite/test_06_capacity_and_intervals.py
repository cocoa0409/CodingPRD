"""Shared-seating aggregate capacity, half-open overlap geometry, the event
inter-event buffer, seat conservation on release, and interval degeneracy.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_food_hall, reserve_seats, release_seats,
    create_planned_event, create_scheduled_event,
    create_seating_allocation_payload, create_marketing_event_payload,
    TEST_USERS,
)

HM = TEST_USERS["hall_manager_headers"]
POS = TEST_USERS["pos_operator_headers"]


class TestSeatingCapacityBoundary:
    """boundary_precision_check / seating_capacity_equality_admitted. Capacity 100,
    70 seats already reserved over the overlapping window."""

    def test_equality_admitted(self, api):
        """PRD §3.6: "The request is admitted only when that concurrent load plus
        the requested `seats` is at most `total_seating_capacity`; equality is
        admitted."

        Design: Difficulty/boundary_precision_check/seating_capacity_equality_admitted
        """
        hall = create_food_hall(total_seating_capacity=100)
        reserve_seats(hall["id"], 70, "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z")
        res = api.create_seating_allocation(
            create_seating_allocation_payload(
                hall["id"], seats=30,
                start_time="2026-06-15T10:30:00Z", end_time="2026-06-15T11:30:00Z"), POS)
        data = validate_success(res, 201)
        assert data["status"] == "RESERVED"

    def test_one_over_capacity_rejected(self, api):
        """PRD §3.6: "A request that would push the total above capacity is rejected
        with `ERR_SEATING_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/seating_capacity_equality_admitted
        """
        hall = create_food_hall(total_seating_capacity=100)
        reserve_seats(hall["id"], 70, "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z")
        res = api.create_seating_allocation(
            create_seating_allocation_payload(
                hall["id"], seats=31,
                start_time="2026-06-15T10:30:00Z", end_time="2026-06-15T11:30:00Z"), POS)
        validate_error(res, "ERR_SEATING_CAPACITY_EXCEEDED")


class TestSeatingHalfOpenOverlap:
    """resource_temporal_overlap / seating_half_open_aggregate_overlap. Capacity 100,
    70 seats reserved over [10:00,12:00)."""

    def test_adjacent_window_does_not_overlap(self, api):
        """PRD §3.6: "Two windows on the same hall overlap when one starts strictly
        before the other ends and the other starts strictly before the first ends;
        two windows that merely touch — one ending exactly when the other begins —
        do not overlap."

        Design: Difficulty/resource_temporal_overlap/seating_half_open_aggregate_overlap
        """
        hall = create_food_hall(total_seating_capacity=100)
        reserve_seats(hall["id"], 70, "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z")
        res = api.create_seating_allocation(
            create_seating_allocation_payload(
                hall["id"], seats=90,
                start_time="2026-06-15T12:00:00Z", end_time="2026-06-15T14:00:00Z"), POS)
        data = validate_success(res, 201)
        assert data["status"] == "RESERVED"

    def test_overlapping_window_over_capacity_rejected(self, api):
        """PRD §3.6: "The concurrent seat load for a requested window is the sum of
        `seats` across all `RESERVED` allocations on the same hall whose windows
        overlap the requested window."

        Design: Difficulty/resource_temporal_overlap/seating_half_open_aggregate_overlap
        """
        hall = create_food_hall(total_seating_capacity=100)
        reserve_seats(hall["id"], 70, "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z")
        res = api.create_seating_allocation(
            create_seating_allocation_payload(
                hall["id"], seats=90,
                start_time="2026-06-15T11:00:00Z", end_time="2026-06-15T13:00:00Z"), POS)
        validate_error(res, "ERR_SEATING_CAPACITY_EXCEEDED")


class TestEventBufferDilatedOverlap:
    """resource_temporal_overlap / event_buffer_dilated_overlap. Buffer 60 min; E1
    scheduled 09:00-12:00."""

    def test_gap_below_buffer_conflicts(self, api):
        """PRD §3.7: "A gap of exactly the buffer length between the two windows is
        admitted; a smaller gap is a conflict and is rejected with
        `ERR_EVENT_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/event_buffer_dilated_overlap
        """
        hall = create_food_hall(common_area_capacity=500, event_buffer_minutes=60)
        create_scheduled_event(hall["id"], name="E1",
                               start_time="2026-07-01T09:00:00Z",
                               end_time="2026-07-01T12:00:00Z",
                               reserved_capacity=100, expected_footfall=300)
        e2 = create_planned_event(hall["id"], name="E2",
                                  start_time="2026-07-01T12:30:00Z",
                                  end_time="2026-07-01T14:00:00Z",
                                  reserved_capacity=100, expected_footfall=200)
        res = api.schedule_marketing_event(e2["id"], HM)
        validate_error(res, "ERR_EVENT_TIME_CONFLICT")

    def test_gap_equal_to_buffer_admitted(self, api):
        """PRD §3.7: "A gap of exactly the buffer length between the two windows is
        admitted; a smaller gap is a conflict and is rejected with
        `ERR_EVENT_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/event_buffer_dilated_overlap
        """
        hall = create_food_hall(common_area_capacity=500, event_buffer_minutes=60)
        create_scheduled_event(hall["id"], name="E1",
                               start_time="2026-07-01T09:00:00Z",
                               end_time="2026-07-01T12:00:00Z",
                               reserved_capacity=100, expected_footfall=300)
        e3 = create_planned_event(hall["id"], name="E3",
                                  start_time="2026-07-01T13:00:00Z",
                                  end_time="2026-07-01T15:00:00Z",
                                  reserved_capacity=100, expected_footfall=200)
        data = validate_success(api.schedule_marketing_event(e3["id"], HM), 200)
        assert data["status"] == "SCHEDULED"


class TestSeatConservation:
    """compensating_invariant / seat_conservation_reserve_then_release. Capacity 100."""

    def test_reserved_seats_occupy_capacity(self, api):
        """PRD §3.6: "The request is admitted only when that concurrent load plus
        the requested `seats` is at most `total_seating_capacity`; equality is
        admitted. A request that would push the total above capacity is rejected
        with `ERR_SEATING_CAPACITY_EXCEEDED`."

        Design: Difficulty/compensating_invariant/seat_conservation_reserve_then_release
        """
        hall = create_food_hall(total_seating_capacity=100)
        reserve_seats(hall["id"], 100, "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z")
        res = api.create_seating_allocation(
            create_seating_allocation_payload(
                hall["id"], seats=1,
                start_time="2026-06-15T10:00:00Z", end_time="2026-06-15T12:00:00Z"), POS)
        validate_error(res, "ERR_SEATING_CAPACITY_EXCEEDED")

    def test_release_restores_full_capacity(self, api):
        """PRD §3.6: "A release always frees exactly the seats it held, so capacity
        is conserved: seats freed by a release, an order rejection, or a posture
        cascade become immediately available to new reservations in that window."

        Design: Difficulty/compensating_invariant/seat_conservation_reserve_then_release
        """
        hall = create_food_hall(total_seating_capacity=100)
        a1 = reserve_seats(hall["id"], 100, "2026-06-15T10:00:00Z", "2026-06-15T12:00:00Z")
        release_seats(a1["id"])
        res = api.create_seating_allocation(
            create_seating_allocation_payload(
                hall["id"], seats=100,
                start_time="2026-06-15T10:00:00Z", end_time="2026-06-15T12:00:00Z"), POS)
        data = validate_success(res, 201)
        assert data["status"] == "RESERVED"


def test_event_over_common_area_capacity_rejected(api):
    """PRD §3.7: "The event's `reserved_capacity` must not exceed the hall's
    `common_area_capacity`, otherwise it is rejected with
    `ERR_COMMON_AREA_CAPACITY_EXCEEDED`."

    Design: Corner/cross_cutting/event_over_common_area_capacity_rejected
    """
    hall = create_food_hall(common_area_capacity=500)
    event = create_planned_event(hall["id"], name="Big",
                                 start_time="2026-07-01T09:00:00Z",
                                 end_time="2026-07-01T12:00:00Z",
                                 reserved_capacity=600, expected_footfall=900)
    res = api.schedule_marketing_event(event["id"], HM)
    validate_error(res, "ERR_COMMON_AREA_CAPACITY_EXCEEDED")


def test_seating_zero_window_returns_interval_invalid(api):
    """PRD §2.10: "A degenerate time interval on a seating allocation or event
    window — where the start is not strictly before the end — returns
    `ERR_INTERVAL_INVALID` (422)."

    Design: Corner/validations/seating_zero_window_returns_invalid_request
    """
    hall = create_food_hall(total_seating_capacity=100)
    res = api.create_seating_allocation(
        create_seating_allocation_payload(
            hall["id"], seats=4,
            start_time="2026-06-15T10:00:00Z", end_time="2026-06-15T10:00:00Z"), POS)
    validate_error(res, "ERR_INTERVAL_INVALID")
