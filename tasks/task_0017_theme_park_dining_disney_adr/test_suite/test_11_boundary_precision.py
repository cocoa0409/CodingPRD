"""Boundary precision — inclusive booking-window open and exclusive Lightning Lane
expiry. Queue A (Difficulty)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    setup_guest_restaurant_plan_session,
    setup_confirmed_reservation,
    create_reservation_payload,
    create_lightning_lane_payload,
    allocate_lightning_lane_payload,
    fetch_lightning_lane,
    make_guest_headers,
    TEST_USERS,
)


# ─── Booking window open instant ──────────────────────────────────────────

class TestBookingWindowOpenBoundary:
    """Difficulty/boundary_precision_check/window_open_at_boundary_inclusive_on_post_reservations"""

    def test_at_window_open_instant_booking_accepted(self, api):
        """PRD §3.3: "The booking window opens, for each calendar visit_date,
        exactly 60 days before that date, at 06:00:00 in the resort timezone. To
        compute the opening instant the platform takes 06:00 local resort time on
        the visit date, subtracts 60 calendar days, and converts the result to
        UTC — because the resort observes DST, the UTC instant of window-open
        drifts across the year. A booking attempt before that instant is rejected
        with ERR_OUTSIDE_BOOKING_WINDOW"

        For visit_date 2026-02-15, 06:00 EST = 11:00:00Z; minus 60 calendar days
        = 2025-12-17T11:00:00Z. At exactly that instant, booking is permitted.

        Design: Difficulty/boundary_precision_check/window_open_at_boundary_inclusive_on_post_reservations
        """
        set_clock("2025-12-17T11:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="EPCOT",
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
            plan_valid_from="2025-12-01T00:00:00Z",
            plan_valid_until="2026-12-31T00:00:00Z",
            visit_date="2026-02-15",
        )
        payload = create_reservation_payload(
            guest_id=guest["id"],
            restaurant_id=restaurant["id"],
            park_session_id=ps["id"],
            dining_plan_id=dp["id"],
            slot_start_utc="2026-02-15T18:00:00Z",
            party_size=2,
        )
        res = api.create_reservation(payload, make_guest_headers(guest["id"]))
        reservation = validate_success(res, expected_status=201)
        assert reservation["status"] == "PENDING"

    def test_one_second_before_window_open_booking_rejected(self, api):
        """PRD §3.3: "A booking attempt before that instant is rejected with
        ERR_OUTSIDE_BOOKING_WINDOW"

        Companion to the inclusive-at-instant test: one second earlier than the
        opening instant, the same booking must be rejected with the
        ERR_OUTSIDE_BOOKING_WINDOW error.

        Design: Difficulty/boundary_precision_check/window_open_at_boundary_inclusive_on_post_reservations
        """
        from test_helpers import validate_error, ApiErrorId
        set_clock("2025-12-17T10:59:59Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="EPCOT",
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
            plan_valid_from="2025-12-01T00:00:00Z",
            plan_valid_until="2026-12-31T00:00:00Z",
            visit_date="2026-02-15",
        )
        payload = create_reservation_payload(
            guest_id=guest["id"],
            restaurant_id=restaurant["id"],
            park_session_id=ps["id"],
            dining_plan_id=dp["id"],
            slot_start_utc="2026-02-15T18:00:00Z",
            party_size=2,
        )
        res = api.create_reservation(payload, make_guest_headers(guest["id"]))
        validate_error(res, ApiErrorId.ERR_OUTSIDE_BOOKING_WINDOW, expected_status=422)


# ─── LL expiry boundary (strict >, exclusive) ─────────────────────────────

class TestLightningLaneExpiryBoundary:
    """Difficulty/boundary_precision_check/lightning_lane_redemption_window_expiry_boundary_on_expiry_sweep"""

    def test_at_redemption_window_end_sweep_does_not_expire(self, api):
        """PRD §3.7: "If neither path runs and redemption_window_end_utc passes
        while the add-on is still in ALLOCATED, an operator-driven expiry sweep
        transitions the add-on from ALLOCATED to EXPIRED."
        PRD §3.8: "The Lightning Lane expiry sweep capability walks every
        LightningLaneAddOn in ALLOCATED whose redemption_window_end_utc is now
        strictly earlier than the current UTC time and runs the ALLOCATED-to-
        EXPIRED transition on each, returning expired_count and expired_addon_ids."

        Design: Difficulty/boundary_precision_check/lightning_lane_redemption_window_expiry_boundary_on_expiry_sweep
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            is_character_dining=False,
            park_code="ANIMAL_KINGDOM",
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        # Allocate the LL — redemption_window_end_utc = slot_end_utc + 60 min
        # = 2026-02-15T18:30:00Z + 60min = 2026-02-15T19:30:00Z.
        ll = validate_success(
            api.create_lightning_lane(
                create_lightning_lane_payload(
                    reservation_id=reservation["id"], tier="SINGLE_PASS",
                ),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        allocated = validate_success(
            api.allocate_lightning_lane(
                ll["id"],
                allocate_lightning_lane_payload(reservation["version"]),
                make_guest_headers(guest["id"]),
            ),
            expected_status=200,
        )
        # PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
        assert allocated["redemption_window_end_utc"] == "2026-02-15T19:30:00.000Z"
        # Set clock to EXACTLY the boundary instant.
        set_clock("2026-02-15T19:30:00Z")
        sweep = validate_success(
            api.lightning_lane_expiry_sweep(TEST_USERS["platform_admin_headers"]),
            expected_status=200,
        )
        assert sweep["expired_count"] == 0
        ll_after = fetch_lightning_lane(ll["id"], guest["id"])
        assert ll_after["status"] == "ALLOCATED"

    def test_one_second_after_redemption_window_end_sweep_expires(self, api):
        """PRD §3.8: "The Lightning Lane expiry sweep capability walks every
        LightningLaneAddOn in ALLOCATED whose redemption_window_end_utc is now
        strictly earlier than the current UTC time and runs the ALLOCATED-to-
        EXPIRED transition on each, returning expired_count and expired_addon_ids."

        Companion strict-comparison test: one second after the boundary, the
        sweep must transition the add-on to EXPIRED.

        Design: Difficulty/boundary_precision_check/lightning_lane_redemption_window_expiry_boundary_on_expiry_sweep
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            is_character_dining=False,
            park_code="ANIMAL_KINGDOM",
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        ll = validate_success(
            api.create_lightning_lane(
                create_lightning_lane_payload(
                    reservation_id=reservation["id"], tier="SINGLE_PASS",
                ),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        validate_success(
            api.allocate_lightning_lane(
                ll["id"],
                allocate_lightning_lane_payload(reservation["version"]),
                make_guest_headers(guest["id"]),
            ),
            expected_status=200,
        )
        # One second past the boundary.
        set_clock("2026-02-15T19:30:01Z")
        sweep = validate_success(
            api.lightning_lane_expiry_sweep(TEST_USERS["platform_admin_headers"]),
            expected_status=200,
        )
        assert sweep["expired_count"] == 1
        ll_after = fetch_lightning_lane(ll["id"], guest["id"])
        assert ll_after["status"] == "EXPIRED"
