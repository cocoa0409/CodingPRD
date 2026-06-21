"""Resource temporal overlap — slot capacity vs guest double-booking. Queue A."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_clock,
    setup_guest_restaurant_plan_session,
    create_guest,
    create_restaurant,
    create_dining_plan,
    create_park_session,
    create_pending_reservation,
    confirm_reservation,
    create_reservation_payload,
    make_guest_headers,
    TEST_USERS,
    ApiErrorId,
)


# ─── Aggregate slot capacity sum ─────────────────────────────────────────

class TestRestaurantSlotCapacityAggregateSum:
    """Difficulty/resource_temporal_overlap/restaurant_slot_capacity_aggregate_seat_sum_half_open_overlap"""

    def test_overflow_aggregate_seat_sum_returns_capacity_exceeded(self, api):
        """PRD §3.3: "Slot capacity is enforced by summing the party_size of every
        other reservation at the same restaurant whose [slot_start_utc, slot_end_utc)
        half-open interval overlaps the candidate's interval and whose status is
        in PENDING, CONFIRMED, CHECKED_IN, or SEATED; if that sum plus the
        candidate's party_size exceeds the restaurant's capacity_per_slot, the
        booking is rejected with ERR_SLOT_CAPACITY_EXCEEDED."

        Design: Difficulty/resource_temporal_overlap/restaurant_slot_capacity_aggregate_seat_sum_half_open_overlap
        """
        set_clock("2026-01-15T12:00:00Z")
        restaurant = create_restaurant(
            name="CapTest", park_code="MAGIC_KINGDOM", capacity_per_slot=4,
            is_character_dining=True, opening_local_time="08:00", closing_local_time="22:00",
        )
        # Guest A — confirmed party_size=3 at the slot.
        # PRD §3.1: email must be lowercase.
        guest_a = create_guest(email="capa@x.com")
        dp_a = create_dining_plan(guest_a["id"], table_service_credits_initial=10)
        ps_a = create_park_session(
            guest_a["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        pending_a = create_pending_reservation(
            guest_a, restaurant, ps_a, dp_a,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=3,
        )
        confirm_reservation(pending_a, guest_a["id"])
        # Guest B — confirmed party_size=1 at same slot. Slot total = 4 (full).
        guest_b = create_guest(email="capb@x.com")
        dp_b = create_dining_plan(guest_b["id"], table_service_credits_initial=10)
        ps_b = create_park_session(
            guest_b["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        pending_b = create_pending_reservation(
            guest_b, restaurant, ps_b, dp_b,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=1,
        )
        confirm_reservation(pending_b, guest_b["id"])
        # Trigger Guest T — attempt party_size=1 at the same slot.
        # Existing 3+1 = 4, candidate +1 → 5 > 4 → reject.
        guest_t = create_guest(email="capt@x.com")
        dp_t = create_dining_plan(guest_t["id"], table_service_credits_initial=10)
        ps_t = create_park_session(
            guest_t["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        payload = create_reservation_payload(
            guest_id=guest_t["id"], restaurant_id=restaurant["id"],
            park_session_id=ps_t["id"], dining_plan_id=dp_t["id"],
            slot_start_utc="2026-02-15T18:00:00Z", party_size=1,
        )
        res = api.create_reservation(payload, make_guest_headers(guest_t["id"]))
        validate_error(res, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED, expected_status=409)

    def test_exact_capacity_match_succeeds(self, api):
        """PRD §3.3: "if that sum plus the candidate's party_size exceeds the
        restaurant's capacity_per_slot, the booking is rejected with
        ERR_SLOT_CAPACITY_EXCEEDED."
        PRD §3.3: "Slot capacity is enforced by summing the party_size of every
        other reservation at the same restaurant whose [slot_start_utc, slot_end_utc)
        half-open interval overlaps the candidate's interval and whose status is
        in PENDING, CONFIRMED, CHECKED_IN, or SEATED"

        Companion: at exactly capacity (sum == capacity_per_slot, not >),
        booking is accepted, isolating the strict "exceeds" comparison rule.

        Design: Difficulty/resource_temporal_overlap/restaurant_slot_capacity_aggregate_seat_sum_half_open_overlap
        """
        set_clock("2026-01-15T12:00:00Z")
        restaurant = create_restaurant(
            name="CapMatch", park_code="MAGIC_KINGDOM", capacity_per_slot=4,
            is_character_dining=False, opening_local_time="11:00", closing_local_time="22:00",
        )
        guest_a = create_guest(email="match_a@x.com")
        dp_a = create_dining_plan(guest_a["id"], table_service_credits_initial=10)
        ps_a = create_park_session(
            guest_a["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        pending_a = create_pending_reservation(
            guest_a, restaurant, ps_a, dp_a,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=3,
        )
        confirm_reservation(pending_a, guest_a["id"])
        # Trigger Guest T — party_size=1; total = 3 + 1 = 4, equals capacity exactly.
        guest_t = create_guest(email="match_t@x.com")
        dp_t = create_dining_plan(guest_t["id"], table_service_credits_initial=10)
        ps_t = create_park_session(
            guest_t["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        payload = create_reservation_payload(
            guest_id=guest_t["id"], restaurant_id=restaurant["id"],
            park_session_id=ps_t["id"], dining_plan_id=dp_t["id"],
            slot_start_utc="2026-02-15T18:00:00Z", party_size=1,
        )
        res = api.create_reservation(payload, make_guest_headers(guest_t["id"]))
        reservation = validate_success(res, expected_status=201)
        assert reservation["status"] == "PENDING"


# ─── Guest double-booking padded buffer ──────────────────────────────────

class TestGuestDoubleBookingPaddedBuffer:
    """Difficulty/resource_temporal_overlap/guest_double_booking_padded_buffer_60min_pairwise_overlap"""

    def test_padded_buffer_60min_overlap_returns_double_booking(self, api):
        """PRD §3.3: "The guest is also blocked from overlapping themselves: if
        the same guest already has a non-terminal reservation (one in PENDING,
        CONFIRMED, CHECKED_IN, or SEATED) whose interval, padded by 60 minutes on
        each side, overlaps the candidate's [slot_start_utc, slot_end_utc)
        interval, the request is rejected with ERR_GUEST_DOUBLE_BOOKING — this
        padded one-dining-slot-per-60-minute rule applies across all four parks,
        not per-park."

        Design: Difficulty/resource_temporal_overlap/guest_double_booking_padded_buffer_60min_pairwise_overlap
        """
        set_clock("2026-01-15T12:00:00Z")
        guest = create_guest(email="dblbook@x.com")
        dp = create_dining_plan(guest["id"], tier="DELUXE", table_service_credits_initial=20)
        r_a = create_restaurant(
            name="Sanaa", park_code="ANIMAL_KINGDOM", capacity_per_slot=20,
            opening_local_time="08:00", closing_local_time="22:00",
        )
        r_b = create_restaurant(
            name="Tiffins", park_code="ANIMAL_KINGDOM", capacity_per_slot=20,
            opening_local_time="08:00", closing_local_time="22:00",
        )
        ps = create_park_session(
            guest["id"], park_code="ANIMAL_KINGDOM", visit_date="2026-02-15",
        )
        # First confirmed reservation at 17:00 → 17:30; padded occupation [16:00, 18:30].
        pending_a = create_pending_reservation(
            guest, r_a, ps, dp,
            slot_start_utc="2026-02-15T17:00:00Z", party_size=2,
        )
        confirm_reservation(pending_a, guest["id"])
        # Candidate at 18:00 → 18:30 at r_b — overlaps padded [16:00, 18:30].
        payload = create_reservation_payload(
            guest_id=guest["id"], restaurant_id=r_b["id"],
            park_session_id=ps["id"], dining_plan_id=dp["id"],
            slot_start_utc="2026-02-15T18:00:00Z", party_size=2,
        )
        res = api.create_reservation(payload, make_guest_headers(guest["id"]))
        validate_error(res, ApiErrorId.ERR_GUEST_DOUBLE_BOOKING, expected_status=409)

    def test_far_apart_non_overlapping_bookings_succeed(self, api):
        """PRD §3.3: "if the same guest already has a non-terminal reservation
        (one in PENDING, CONFIRMED, CHECKED_IN, or SEATED) whose interval,
        padded by 60 minutes on each side, overlaps the candidate's
        [slot_start_utc, slot_end_utc) interval, the request is rejected with
        ERR_GUEST_DOUBLE_BOOKING"

        Companion: a booking outside the padded buffer must succeed, isolating
        the "60-minute padding overlap" rule from a generic per-guest cap.

        Design: Difficulty/resource_temporal_overlap/guest_double_booking_padded_buffer_60min_pairwise_overlap
        """
        set_clock("2026-01-15T12:00:00Z")
        guest = create_guest(email="dblbook_ok@x.com")
        dp = create_dining_plan(guest["id"], tier="DELUXE", table_service_credits_initial=20)
        r_a = create_restaurant(
            name="Sanaa2", park_code="ANIMAL_KINGDOM", capacity_per_slot=20,
            opening_local_time="08:00", closing_local_time="22:00",
        )
        r_b = create_restaurant(
            name="Tiffins2", park_code="ANIMAL_KINGDOM", capacity_per_slot=20,
            opening_local_time="08:00", closing_local_time="22:00",
        )
        ps = create_park_session(
            guest["id"], park_code="ANIMAL_KINGDOM", visit_date="2026-02-15",
        )
        # First booking 14:00Z-14:30Z (09:00-09:30 EST) → padded [13:00Z, 15:30Z].
        # Restaurant opens 08:00 EST = 13:00Z in Feb (EST, UTC-5).
        pending_a = create_pending_reservation(
            guest, r_a, ps, dp,
            slot_start_utc="2026-02-15T14:00:00Z", party_size=2,
        )
        confirm_reservation(pending_a, guest["id"])
        # Second booking at 22:00Z-22:30Z (17:00-17:30 EST) — well outside [13:00Z, 15:30Z].
        payload = create_reservation_payload(
            guest_id=guest["id"], restaurant_id=r_b["id"],
            park_session_id=ps["id"], dining_plan_id=dp["id"],
            slot_start_utc="2026-02-15T22:00:00Z", party_size=2,
        )
        res = api.create_reservation(payload, make_guest_headers(guest["id"]))
        second = validate_success(res, expected_status=201)
        assert second["status"] == "PENDING"
