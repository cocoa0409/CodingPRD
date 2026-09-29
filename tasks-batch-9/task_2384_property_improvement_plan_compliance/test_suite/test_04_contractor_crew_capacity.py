"""Half-open crew booking intervals and the contractor's concurrent-occupancy limit."""

from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_field_equals,
    book_crew,
    contractor_booking_payload,
    issued_plan,
    list_rows,
    register_contractor,
    schedule_phase,
    validate_error,
    validate_success,
)


@pytest.fixture
def phase_and_two_slot_contractor(api):
    """A planned closure window and a general contractor allowed two concurrent engagements."""
    scenario = issued_plan(
        api,
        [
            {
                "key": "loading_dock",
                "category": "BACK_OF_HOUSE",
                "standards_reference": "BOH-7.7.1",
                "brand_estimated_cost_cents": 500000,
            }
        ],
        legal_name="Kingsport Hotels LLC",
        contact_email="construction@kingsporthotels.example",
    )
    phase = schedule_phase(
        api,
        scenario,
        phase_number=1,
        start_date="2026-09-01",
        end_date="2026-09-10",
        rooms_out_of_service=10,
    )
    contractor = register_contractor(
        api,
        name="Grantham General Contracting",
        trade="GENERAL",
        brand_approved=False,
        max_concurrent_bookings=2,
    )
    return scenario, phase, contractor


class TestContractorConcurrentOccupancy:
    def test_a_crew_booking_is_created_occupied(self, api, phase_and_two_slot_contractor):
        """"A booking is created in `BOOKED`; `CANCELLED` and `COMPLETED` are reached only through
        the phase cascades above". "The interval is **half-open**: the start instant is occupied
        and the end instant is not."

        Design: Difficulty/resource_temporal_overlap/contractor_capacity_half_open_intervals_allow_adjacency
        """
        scenario, phase, contractor = phase_and_two_slot_contractor

        booking = book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T08:00:00Z",
            end_datetime="2026-09-02T16:00:00Z",
            crew_size=4,
        )

        assert_field_equals(booking, "status", "BOOKED", "booking")

    def test_a_second_genuinely_overlapping_booking_fits_under_a_limit_of_two(
        self, api, phase_and_two_slot_contractor
    ):
        """"a contractor whose `max_concurrent_bookings` is 2 admits a second genuinely
        overlapping booking but refuses the third." "The occupant count is the number of that
        contractor's bookings still in `BOOKED` whose interval strictly overlaps the requested one
        — strictly, meaning the new start is earlier than the existing end *and* the existing start
        is earlier than the new end."

        Design: Difficulty/resource_temporal_overlap/contractor_capacity_half_open_intervals_allow_adjacency
        """
        scenario, phase, contractor = phase_and_two_slot_contractor
        book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T08:00:00Z",
            end_datetime="2026-09-02T16:00:00Z",
        )

        second = book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T12:00:00Z",
            end_datetime="2026-09-02T20:00:00Z",
        )

        assert_field_equals(second, "status", "BOOKED", "second booking")

    def test_the_third_concurrent_booking_is_refused(self, api, phase_and_two_slot_contractor):
        """"If that count is already at or above the contractor's `max_concurrent_bookings`, the
        booking is refused with `ERR_CONTRACTOR_DOUBLE_BOOKED` (409)."

        Design: Difficulty/resource_temporal_overlap/contractor_capacity_half_open_intervals_allow_adjacency
        """
        scenario, phase, contractor = phase_and_two_slot_contractor
        book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T08:00:00Z",
            end_datetime="2026-09-02T16:00:00Z",
        )
        book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T12:00:00Z",
            end_datetime="2026-09-02T20:00:00Z",
        )

        response = api.create_contractor_booking(
            contractor_booking_payload(
                contractor["id"],
                phase["id"],
                start_datetime="2026-09-02T13:00:00Z",
                end_datetime="2026-09-02T15:00:00Z",
            ),
            scenario.owner_headers,
        )

        validate_error(response, ApiErrorId.ERR_CONTRACTOR_DOUBLE_BOOKED, 409)

    def test_a_booking_starting_at_another_s_end_instant_is_always_admitted(
        self, api, phase_and_two_slot_contractor
    ):
        """"a booking starting exactly at another's end instant does not overlap and is always
        admitted". "No buffer is applied."

        Design: Difficulty/resource_temporal_overlap/contractor_capacity_half_open_intervals_allow_adjacency
        """
        scenario, phase, contractor = phase_and_two_slot_contractor
        book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T08:00:00Z",
            end_datetime="2026-09-02T16:00:00Z",
        )
        earlier = book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T12:00:00Z",
            end_datetime="2026-09-02T20:00:00Z",
        )

        adjacent = validate_success(
            api.create_contractor_booking(
                contractor_booking_payload(
                    contractor["id"],
                    phase["id"],
                    start_datetime="2026-09-02T20:00:00Z",
                    end_datetime="2026-09-03T04:00:00Z",
                ),
                scenario.owner_headers,
            ),
            expected_status=201,
        )

        assert_field_equals(adjacent, "status", "BOOKED", "adjacent booking")
        assert adjacent["start_datetime"] == earlier["end_datetime"], (
            "the adjacent booking should start at the instant the earlier one releases: "
            f"{adjacent['start_datetime']!r} vs {earlier['end_datetime']!r}"
        )

    def test_only_the_admitted_engagements_occupy_the_contractor(
        self, api, phase_and_two_slot_contractor
    ):
        """"which means the filtered booking list is the only channel through which those
        cascade-driven states can be observed." A refused booking is never created, since the
        request "is refused with `ERR_CONTRACTOR_DOUBLE_BOOKED` (409)".

        Design: Difficulty/resource_temporal_overlap/contractor_capacity_half_open_intervals_allow_adjacency
        """
        scenario, phase, contractor = phase_and_two_slot_contractor
        book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T08:00:00Z",
            end_datetime="2026-09-02T16:00:00Z",
        )
        book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T12:00:00Z",
            end_datetime="2026-09-02T20:00:00Z",
        )
        validate_error(
            api.create_contractor_booking(
                contractor_booking_payload(
                    contractor["id"],
                    phase["id"],
                    start_datetime="2026-09-02T13:00:00Z",
                    end_datetime="2026-09-02T15:00:00Z",
                ),
                scenario.owner_headers,
            ),
            ApiErrorId.ERR_CONTRACTOR_DOUBLE_BOOKED,
            409,
        )
        book_crew(
            api,
            scenario,
            contractor["id"],
            phase["id"],
            start_datetime="2026-09-02T20:00:00Z",
            end_datetime="2026-09-03T04:00:00Z",
        )

        rows, meta = list_rows(api, "list_contractor_bookings", contractor_id=contractor["id"])

        assert meta["total_count"] == 3, (
            f"three bookings should have been admitted for this contractor, got {meta}"
        )
        assert all(row["status"] == "BOOKED" for row in rows), (
            f"every admitted booking should still be BOOKED, got {[r['status'] for r in rows]}"
        )
