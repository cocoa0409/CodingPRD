"""Itinerary booking: PRD §3.3 (segment book / change / cancel), policy
eligibility, segment-within-trip, transport overlap, hotel-night overlap,
budget overrun, and the APPROVED → BOOKING_LOCKED transition.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approved_application,
    assert_itinerary_segment,
    book_segment_payload,
    get_success_data,
    seed_eligible_option,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import book_segment


# ---------------------------------------------------------------------------
# First booking transitions APPROVED → BOOKING_LOCKED (PRD §3.3)
# ---------------------------------------------------------------------------
class TestBookingLockTransition:

    def test_first_booking_transitions_application_to_booking_locked(self, api):
        """PRD §3.3: "The first successful booking against an APPROVED
        application transitions the application from APPROVED to
        BOOKING_LOCKED."

        Claim: after the first segment is booked, application status is
        BOOKING_LOCKED.
        """
        cast, approved = approved_application(estimated_budget=4_500.00)
        assert approved["status"] == "APPROVED"
        seg = book_segment(
            cast, approved["id"],
            segment_type="FLIGHT", cost=500.00,
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T13:00:00.000Z",
        )
        assert_itinerary_segment(seg)
        assert seg["status"] == "ACTIVE"

        # The parent application should now be BOOKING_LOCKED.
        app_after = validate_success(
            api.get_travel_application(approved["id"], cast.applicant_headers),
        )
        assert app_after["status"] == "BOOKING_LOCKED", (
            "PRD §3.3: first successful booking transitions APPROVED → BOOKING_LOCKED"
        )

    def test_total_booked_cost_aggregates_active_segments(self, api):
        """PRD §3.3: "Every successful create / change / cancel against
        the itinerary recomputes the application's total_booked_cost as
        the sum of the cost of all segments under the application whose
        status is ACTIVE."

        Claim: total_booked_cost == sum of ACTIVE segment costs after 2 bookings.
        """
        cast, approved = approved_application(estimated_budget=4_500.00)
        book_segment(
            cast, approved["id"], segment_type="FLIGHT", cost=500.00,
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T13:00:00.000Z",
        )
        book_segment(
            cast, approved["id"], segment_type="HOTEL", cost=300.00,
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-03T11:00:00.000Z",
        )
        app = validate_success(
            api.get_travel_application(approved["id"], cast.applicant_headers),
        )
        assert app["total_booked_cost"] == pytest.approx(800.00, abs=0.01)


# ---------------------------------------------------------------------------
# Policy eligibility (PRD §3.3 priority 1, §1.4 priority 7)
# ---------------------------------------------------------------------------
class TestPolicyEligibility:

    def test_unknown_option_code_rejected(self, api):
        """PRD §3.3: "The submitted option_code MUST appear in the
        policy-eligible option set for the pair (segment_type,
        applicant's employee_level); otherwise the booking is rejected
        with ERR_OPTION_NOT_ELIGIBLE."

        Claim: a never-seeded option_code triggers ERR_OPTION_NOT_ELIGIBLE.
        """
        cast, approved = approved_application(estimated_budget=4_500.00)
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="FLIGHT",
                option_code="UNKNOWN-FLIGHT-OPTION-XYZ",
                cost=500.00,
                start_at="2025-06-01T10:00:00.000Z",
                end_at="2025-06-01T13:00:00.000Z",
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_OPTION_NOT_ELIGIBLE.value)


# ---------------------------------------------------------------------------
# Segment-within-trip (PRD §3.3 step 2)
# ---------------------------------------------------------------------------
class TestSegmentWithinTrip:

    def test_segment_before_planned_start_rejected(self, api):
        """PRD §3.3: "Both start_at and end_at MUST lie within the
        closed interval [planned_start, planned_end] of the application;
        otherwise ERR_SEGMENT_OUTSIDE_TRIP."

        Claim: segment whose start_at < planned_start → ERR_SEGMENT_OUTSIDE_TRIP.
        """
        cast, approved = approved_application(
            planned_start="2025-06-01T09:00:00.000Z",
            planned_end="2025-06-04T18:00:00.000Z",
            estimated_budget=4_500.00,
        )
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="FLIGHT",
                option_code="OPT-FLIGHT-001",
                start_at="2025-05-30T10:00:00.000Z",
                end_at="2025-06-01T10:00:00.000Z",
                cost=500.00,
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_OUTSIDE_TRIP.value)

    def test_segment_after_planned_end_rejected(self, api):
        """PRD §3.3: "Both start_at and end_at MUST lie within the
        closed interval [planned_start, planned_end] of the application;
        otherwise ERR_SEGMENT_OUTSIDE_TRIP."

        Claim: segment whose end_at > planned_end → ERR_SEGMENT_OUTSIDE_TRIP.
        """
        cast, approved = approved_application(
            planned_start="2025-06-01T09:00:00.000Z",
            planned_end="2025-06-04T18:00:00.000Z",
            estimated_budget=4_500.00,
        )
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="FLIGHT",
                option_code="OPT-FLIGHT-001",
                start_at="2025-06-04T17:00:00.000Z",
                end_at="2025-06-05T20:00:00.000Z",
                cost=500.00,
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_OUTSIDE_TRIP.value)


# ---------------------------------------------------------------------------
# Transport overlap (closed–closed) (PRD §3.3 step 3)
# ---------------------------------------------------------------------------
class TestTransportOverlap:

    def test_adjacent_endpoints_allowed(self, api):
        """PRD §3.3: "Equal endpoints (one segment ending at exactly the
        moment the next begins) are permitted."

        Claim: two transport segments sharing an exact endpoint succeed.
        """
        cast, approved = approved_application(estimated_budget=4_500.00)
        book_segment(
            cast, approved["id"], segment_type="FLIGHT",
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T12:00:00.000Z",
            cost=200.00,
        )
        # Second segment starts exactly when first ends — adjacency permitted.
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="TRAIN", option_code="OPT-TRAIN-001",
                start_at="2025-06-01T12:00:00.000Z",
                end_at="2025-06-01T15:00:00.000Z",
                cost=200.00,
            ),
            cast.applicant_headers,
        )
        validate_success(res, expected_status=201)

    def test_strict_overlap_rejected(self, api):
        """PRD §3.3: "Two ACTIVE segments under the same application
        whose segment_type is in FLIGHT, TRAIN, or CAR MUST NOT have
        time intervals that strictly overlap."

        Claim: TRAIN segment overlapping a FLIGHT segment → ERR_SEGMENT_TIME_OVERLAP.
        """
        cast, approved = approved_application(estimated_budget=4_500.00)
        book_segment(
            cast, approved["id"], segment_type="FLIGHT",
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T12:00:00.000Z",
            cost=200.00,
        )
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="TRAIN", option_code="OPT-TRAIN-001",
                start_at="2025-06-01T11:30:00.000Z",
                end_at="2025-06-01T14:00:00.000Z",
                cost=200.00,
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_SEGMENT_TIME_OVERLAP.value)


# ---------------------------------------------------------------------------
# Hotel night overlap (half-open) (PRD §3.3 step 4)
# ---------------------------------------------------------------------------
class TestHotelNightOverlap:

    def test_hotel_checkout_equals_next_checkin_allowed(self, api):
        """PRD §3.3: "Two ACTIVE HOTEL segments under the same application
        MUST NOT have overlapping [start_at, end_at) night intervals;
        that interval is half-open, so checkout day may equal next
        check-in day."

        Claim: two HOTEL stays whose endpoints coincide are allowed.
        """
        cast, approved = approved_application(
            planned_start="2025-06-01T09:00:00.000Z",
            planned_end="2025-06-08T18:00:00.000Z",
            estimated_budget=4_500.00,
        )
        book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-03T11:00:00.000Z",
            cost=400.00,
        )
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="HOTEL", option_code="OPT-HOTEL-001",
                start_at="2025-06-03T11:00:00.000Z",
                end_at="2025-06-05T11:00:00.000Z",
                cost=400.00,
            ),
            cast.applicant_headers,
        )
        validate_success(res, expected_status=201)

    def test_hotel_overlap_rejected(self, api):
        """PRD §3.3: "A violation is ERR_HOTEL_NIGHT_OVERLAP."

        Claim: two HOTEL stays with 1-minute overlap → ERR_HOTEL_NIGHT_OVERLAP.
        """
        cast, approved = approved_application(
            planned_start="2025-06-01T09:00:00.000Z",
            planned_end="2025-06-08T18:00:00.000Z",
            estimated_budget=4_500.00,
        )
        book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-03T11:00:00.000Z",
            cost=400.00,
        )
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="HOTEL", option_code="OPT-HOTEL-001",
                start_at="2025-06-03T10:59:00.000Z",
                end_at="2025-06-05T11:00:00.000Z",
                cost=400.00,
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_HOTEL_NIGHT_OVERLAP.value)


# ---------------------------------------------------------------------------
# Budget overrun (PRD §3.3 step 5)
# ---------------------------------------------------------------------------
class TestBudgetOverrun:

    def test_booking_at_120_percent_boundary_succeeds(self, api):
        """PRD §3.3: "The recomputed total_booked_cost after this insert
        MUST NOT exceed the application's estimated_budget multiplied by
        the budget overrun factor of 1.20; otherwise the insert is
        rejected with ERR_BUDGET_OVERRUN."

        Claim: with budget=1000, total=1200.00 (= 1000 * 1.20) succeeds
        (boundary is <=, not strict <).
        """
        cast, approved = approved_application(estimated_budget=1_000.00)
        book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=900.00,
        )
        # Bring total exactly to 1200.00 — the cap is inclusive.
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="FLIGHT", option_code="OPT-FLIGHT-001",
                start_at="2025-06-02T15:00:00.000Z",
                end_at="2025-06-02T18:00:00.000Z",
                cost=300.00,
            ),
            cast.applicant_headers,
        )
        validate_success(res, expected_status=201)
        app = validate_success(
            api.get_travel_application(approved["id"], cast.applicant_headers),
        )
        assert app["total_booked_cost"] == pytest.approx(1_200.00, abs=0.01)

    def test_booking_one_cent_over_120_percent_rejected(self, api):
        """PRD §3.3: "the budget overrun factor of 1.20; otherwise the
        insert is rejected with ERR_BUDGET_OVERRUN."

        Claim: with budget=1000 and total at 1200.00, a 0.01 booking
        making total=1200.01 → ERR_BUDGET_OVERRUN.
        """
        cast, approved = approved_application(estimated_budget=1_000.00)
        book_segment(
            cast, approved["id"], segment_type="HOTEL",
            start_at="2025-06-01T15:00:00.000Z",
            end_at="2025-06-02T11:00:00.000Z",
            cost=900.00,
        )
        book_segment(
            cast, approved["id"], segment_type="FLIGHT",
            start_at="2025-06-02T15:00:00.000Z",
            end_at="2025-06-02T18:00:00.000Z",
            cost=300.00,
        )
        # Now try a 0.01 booking that would push total to 1200.01.
        res = api.book_itinerary(
            approved["id"],
            book_segment_payload(
                segment_type="CAR", option_code="OPT-CAR-001",
                start_at="2025-06-03T08:00:00.000Z",
                end_at="2025-06-03T09:00:00.000Z",
                cost=0.01,
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_BUDGET_OVERRUN.value)
        # The rejection must leave total_booked_cost unchanged.
        app_after = validate_success(
            api.get_travel_application(approved["id"], cast.applicant_headers),
        )
        assert app_after["total_booked_cost"] == pytest.approx(1_200.00, abs=0.01)


# ---------------------------------------------------------------------------
# Change and cancel (PRD §3.3)
# ---------------------------------------------------------------------------
class TestChangeAndCancel:

    def test_change_marks_old_changed_and_inserts_new_active(self, api):
        """PRD §3.3: "Change is a record-preserving replacement: the old
        ItinerarySegment row is moved from ACTIVE to CHANGED, and a new
        row is inserted in ACTIVE with its prior_segment_id set to the
        id of the row it superseded."

        Claim: after /change, old seg is CHANGED, new ACTIVE row has
        prior_segment_id == old.id.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        seg = book_segment(
            cast, approved["id"], segment_type="FLIGHT",
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T13:00:00.000Z",
            cost=500.00,
        )
        new_seg = validate_success(
            api.change_itinerary(
                approved["id"], seg["id"],
                book_segment_payload(
                    segment_type="FLIGHT", option_code="OPT-FLIGHT-001",
                    start_at="2025-06-01T11:00:00.000Z",
                    end_at="2025-06-01T14:00:00.000Z",
                    cost=600.00,
                ),
                cast.applicant_headers,
            ),
        )
        assert new_seg["status"] == "ACTIVE"
        assert new_seg["prior_segment_id"] == seg["id"]

        # List segments to confirm old is CHANGED.
        from test_helpers import validate_paginated
        data, _meta = validate_paginated(
            api.list_itineraries(
                approved["id"], cast.applicant_headers,
            )
        )
        old_row = next(s for s in data if s["id"] == seg["id"])
        assert old_row["status"] == "CHANGED"

    def test_cancel_moves_segment_to_cancelled(self, api):
        """PRD §3.3: "Cancel is simpler: the ItinerarySegment moves from
        ACTIVE to CANCELLED, total_booked_cost is recomputed."

        Claim: cancel transitions the segment to CANCELLED.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        seg = book_segment(
            cast, approved["id"], segment_type="FLIGHT",
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T13:00:00.000Z",
            cost=500.00,
        )
        cancelled_seg = validate_success(
            api.cancel_itinerary(
                approved["id"], seg["id"], cast.applicant_headers,
            ),
        )
        assert cancelled_seg["status"] == "CANCELLED"

        app = validate_success(
            api.get_travel_application(approved["id"], cast.applicant_headers),
        )
        assert app["total_booked_cost"] == pytest.approx(0.00, abs=0.01)

    def test_change_on_changed_row_rejected(self, api):
        """PRD §3.3: "for any of the three itinerary operations (book,
        change, cancel), the segment must currently be in ACTIVE for
        change and cancel to apply; an attempt to change a CHANGED or
        CANCELLED row is ERR_INVALID_STATE."

        Claim: /change on a CHANGED segment → ERR_INVALID_STATE.
        """
        from test_helpers.fixtures import book_segment
        cast, approved = approved_application(estimated_budget=4_500.00)
        seg = book_segment(
            cast, approved["id"], segment_type="FLIGHT",
            start_at="2025-06-01T10:00:00.000Z",
            end_at="2025-06-01T13:00:00.000Z",
            cost=500.00,
        )
        # Change once → seg is now CHANGED.
        get_success_data(
            api.change_itinerary(
                approved["id"], seg["id"],
                book_segment_payload(
                    segment_type="FLIGHT", option_code="OPT-FLIGHT-001",
                    start_at="2025-06-01T11:00:00.000Z",
                    end_at="2025-06-01T14:00:00.000Z",
                    cost=600.00,
                ),
                cast.applicant_headers,
            ),
        )
        # Second change on the original (CHANGED) seg must fail.
        res = api.change_itinerary(
            approved["id"], seg["id"],
            book_segment_payload(
                segment_type="FLIGHT", option_code="OPT-FLIGHT-001",
                start_at="2025-06-01T12:00:00.000Z",
                end_at="2025-06-01T15:00:00.000Z",
                cost=700.00,
            ),
            cast.applicant_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
