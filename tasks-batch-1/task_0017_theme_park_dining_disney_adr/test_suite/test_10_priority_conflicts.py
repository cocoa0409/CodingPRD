"""Validation-priority conflict pairs — Queue A (Difficulty)."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    set_clock,
    setup_guest_restaurant_plan_session,
    create_pending_reservation,
    confirm_reservation,
    create_park_session,
    drive_guest_no_show_count,
    create_guest,
    create_restaurant,
    create_dining_plan,
    create_reservation_payload,
    fetch_guest,
    make_guest_headers,
    TEST_USERS,
    ApiErrorId,
)


# ─── State vs Fiscal precedence (confirm on NO_SHOW with no credits) ─────

class TestStateBeforeFiscalPrecedence:
    """Difficulty/priority_pair_validation_conflict/state_vs_fiscal_priority_conflict_check_in_no_show"""

    def test_confirm_no_show_reservation_returns_invalid_state_not_insufficient_credits(self, api):
        """PRD §2.8: "Only after all six gates pass does the platform evaluate
        domain rules — guest-suspension first (ERR_GUEST_SUSPENDED), then
        allergen-shape validation, then temporal rules in the order window-open
        / past-date / restaurant hours / slot-grid alignment, then capacity
        (ERR_SLOT_CAPACITY_EXCEEDED), then guest-side double-booking
        (ERR_GUEST_DOUBLE_BOOKING), then park-session referential consistency
        (ERR_PARK_SESSION_MISMATCH), then fiscal rules (insufficient credits,
        plan coverage), then the add-on uniqueness and party-size feasibility
        constraints."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_priority_conflict_check_in_no_show
        """
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="HOLLYWOOD_STUDIOS",
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=1,  # not enough for anything beyond 1 credit
        )
        pending = create_pending_reservation(
            guest, restaurant, ps, dp,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=1,
        )
        confirm_reservation(pending, guest["id"])
        # Drive it to NO_SHOW.
        set_clock("2026-02-15T19:00:00Z")
        api.mark_no_show_reservation(pending["id"], TEST_USERS["platform_admin_headers"])
        # Now attempt confirm again — both state AND fiscal would fail; state wins.
        res = api.confirm_reservation(pending["id"], make_guest_headers(guest["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_confirm_no_show_reservation_does_not_return_insufficient_credits(self, api):
        """PRD §2.8: "The lower the priority number on a rule, the earlier it
        fires; the first failing rule is the one whose error_id and HTTP status
        the caller sees."

        Companion to the positive precedence test: explicitly confirms the LOWER-
        precedence error (ERR_INSUFFICIENT_CREDITS, a fiscal rule) is NOT what
        the caller sees when state is also failing.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_priority_conflict_check_in_no_show
        """
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="HOLLYWOOD_STUDIOS",
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=1,
        )
        pending = create_pending_reservation(
            guest, restaurant, ps, dp,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=1,
        )
        confirm_reservation(pending, guest["id"])
        set_clock("2026-02-15T19:00:00Z")
        api.mark_no_show_reservation(pending["id"], TEST_USERS["platform_admin_headers"])
        res = api.confirm_reservation(pending["id"], make_guest_headers(guest["id"]))
        # Verify it is NOT the lower-priority fiscal error.
        assert res.status_code == 409, f"expected 409, got {res.status_code}"
        body = res.json()
        assert body["data"]["error_id"] == "ERR_INVALID_STATE"
        assert body["data"]["error_id"] != "ERR_INSUFFICIENT_CREDITS"


# ─── Safety vs Temporal (suspended guest + outside-window booking) ───────

class TestSafetyBeforeTemporalPrecedence:
    """Difficulty/priority_pair_validation_conflict/safety_vs_temporal_priority_conflict_guest_suspended_outside_window"""

    def test_suspended_guest_outside_window_returns_guest_suspended(self, api):
        """PRD §2.8: "Only after all six gates pass does the platform evaluate
        domain rules — guest-suspension first (ERR_GUEST_SUSPENDED), then
        allergen-shape validation, then temporal rules in the order window-open
        / past-date / restaurant hours / slot-grid alignment"
        PRD §3.1: "once suspended the guest is barred from creating new
        reservations or Lightning Lane add-ons — those attempts return
        ERR_GUEST_SUSPENDED even when every other validation would have passed."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_priority_conflict_guest_suspended_outside_window
        """
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="ANIMAL_KINGDOM",
            is_character_dining=True,
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=20,
            plan_valid_until="2027-12-31T00:00:00Z",
            visit_date="2026-01-31",
        )
        # Drive guest to SUSPENDED (5 prior no-shows).
        drive_guest_no_show_count(
            guest, restaurant, dp, num_strikes=5,
            park_code="ANIMAL_KINGDOM", base_date="2026-02-01",
        )
        suspended = fetch_guest(guest["id"])
        assert suspended["status"] == "SUSPENDED"
        # Reset clock to a normal date; create a fresh future park session.
        set_clock("2026-02-15T12:00:00Z")
        far_ps = create_park_session(
            guest["id"], park_code="ANIMAL_KINGDOM", visit_date="2027-01-01",
        )
        # Trigger: booking for slot WAY outside the 60-day window AND with suspended guest.
        payload = create_reservation_payload(
            guest_id=guest["id"],
            restaurant_id=restaurant["id"],
            park_session_id=far_ps["id"],
            dining_plan_id=dp["id"],
            slot_start_utc="2027-01-01T18:00:00Z",
            party_size=1,
        )
        res = api.create_reservation(payload, make_guest_headers(guest["id"]))
        validate_error(res, ApiErrorId.ERR_GUEST_SUSPENDED, expected_status=403)

    def test_suspended_guest_outside_window_does_not_return_outside_booking_window(self, api):
        """PRD §2.8: "The lower the priority number on a rule, the earlier it
        fires; the first failing rule is the one whose error_id and HTTP status
        the caller sees."

        Companion negative-precedence assertion: the temporal rule
        ERR_OUTSIDE_BOOKING_WINDOW must NOT be reported when the higher-priority
        safety rule (ERR_GUEST_SUSPENDED) is also failing.

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_priority_conflict_guest_suspended_outside_window
        """
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="ANIMAL_KINGDOM",
            is_character_dining=True,
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=20,
            plan_valid_until="2027-12-31T00:00:00Z",
            visit_date="2026-01-31",
        )
        drive_guest_no_show_count(
            guest, restaurant, dp, num_strikes=5,
            park_code="ANIMAL_KINGDOM", base_date="2026-02-01",
        )
        set_clock("2026-02-15T12:00:00Z")
        far_ps = create_park_session(
            guest["id"], park_code="ANIMAL_KINGDOM", visit_date="2027-01-01",
        )
        payload = create_reservation_payload(
            guest_id=guest["id"],
            restaurant_id=restaurant["id"],
            park_session_id=far_ps["id"],
            dining_plan_id=dp["id"],
            slot_start_utc="2027-01-01T18:00:00Z",
            party_size=1,
        )
        res = api.create_reservation(payload, make_guest_headers(guest["id"]))
        assert res.status_code == 403, f"expected 403, got {res.status_code}"
        body = res.json()
        assert body["data"]["error_id"] == "ERR_GUEST_SUSPENDED"
        assert body["data"]["error_id"] != "ERR_OUTSIDE_BOOKING_WINDOW"
