"""Cross-entity state dependencies — Queue A (Difficulty)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    set_clock,
    setup_pending_reservation,
    setup_confirmed_reservation,
    create_lightning_lane_payload,
    allocate_lightning_lane_payload,
    fetch_reservation,
    fetch_lightning_lane,
    make_guest_headers,
    TEST_USERS,
    ApiErrorId,
)


# ─── Reservation.confirm requires ParkSession not CLOSED ─────────────────

class TestConfirmRequiresParkSessionNotClosed:
    """Difficulty/cross_entity_state_dependency/reservation_confirm_requires_park_session_not_closed"""

    def test_confirm_after_park_session_closed_returns_invalid_state(self, api):
        """PRD §3.4: "Confirmation requires the reservation to still be in PENDING,
        the underlying ParkSession to be in NOT_STARTED or ACTIVE, and the
        booking Guest to still be in ACTIVE status."

        Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_park_session_not_closed
        """
        # Setup: Pending reservation, park session activated then closed.
        guest, restaurant, dp, ps, pending = setup_pending_reservation(
            party_size=2,
            slot_start_utc="2026-02-15T22:00:00Z",
            park_code="ANIMAL_KINGDOM",
            visit_date="2026-02-15",
            opening_local_time="08:00",
            closing_local_time="23:00",
            initial_clock="2026-01-15T12:00:00Z",
        )
        # Activate the park session on the visit_date.
        set_clock("2026-02-15T13:00:00Z")
        api.activate_park_session(ps["id"], make_guest_headers(guest["id"]))
        # Close it before confirm.
        set_clock("2026-02-15T20:00:00Z")
        api.close_park_session(ps["id"], make_guest_headers(guest["id"]))
        # Now confirm — should fail with ERR_INVALID_STATE.
        res = api.confirm_reservation(pending["id"], make_guest_headers(guest["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        # Reservation must still be PENDING.
        fetched = fetch_reservation(pending["id"], guest["id"])
        assert fetched["status"] == "PENDING"

    def test_confirm_remains_in_pending_after_closed_session_attempt(self, api):
        """PRD §3.4: "Confirmation requires the reservation to still be in PENDING,
        the underlying ParkSession to be in NOT_STARTED or ACTIVE, and the
        booking Guest to still be in ACTIVE status."
        PRD §3.4: "On a successful commit, the platform sets Reservation.credits_held
        to the restaurant's dining_plan_credit_cost multiplied by the reservation's
        current party_size"

        Companion: when confirm fails on cross-entity state precondition, no
        credit hold occurs (the credit-hold side effect attaches to the
        "successful commit" branch only).

        Design: Difficulty/cross_entity_state_dependency/reservation_confirm_requires_park_session_not_closed
        """
        guest, restaurant, dp, ps, pending = setup_pending_reservation(
            party_size=2,
            slot_start_utc="2026-02-15T22:00:00Z",
            park_code="ANIMAL_KINGDOM",
            visit_date="2026-02-15",
            opening_local_time="08:00",
            closing_local_time="23:00",
            initial_clock="2026-01-15T12:00:00Z",
        )
        set_clock("2026-02-15T13:00:00Z")
        api.activate_park_session(ps["id"], make_guest_headers(guest["id"]))
        set_clock("2026-02-15T20:00:00Z")
        api.close_park_session(ps["id"], make_guest_headers(guest["id"]))
        api.confirm_reservation(pending["id"], make_guest_headers(guest["id"]))
        fetched = fetch_reservation(pending["id"], guest["id"])
        assert fetched["status"] == "PENDING"
        assert fetched["credits_held"] == 0


# ─── LL.allocate requires Reservation == CONFIRMED ───────────────────────

class TestAllocateRequiresReservationConfirmed:
    """Difficulty/cross_entity_state_dependency/lightning_lane_allocate_requires_reservation_confirmed

    Tests the allocate-time cross-entity precondition: even with an LL in
    REQUESTED, allocation requires the parent Reservation to be CONFIRMED. We
    drive the reservation OUT of CONFIRMED to a state that is unambiguously
    not-CONFIRMED (NO_SHOW), preserving the LL in REQUESTED, and then attempt
    allocate.
    """

    def test_allocate_after_reservation_no_show_returns_invalid_state(self, api):
        """PRD §3.7: "Allocation requires the underlying reservation to still be
        in CONFIRMED and is OCC-guarded by expected_reservation_version (see
        §2.7); a mismatch yields ERR_STALE_VERSION (HTTP 412)."

        Design: Difficulty/cross_entity_state_dependency/lightning_lane_allocate_requires_reservation_confirmed
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            park_code="HOLLYWOOD_STUDIOS",
            is_character_dining=False,
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        # Create LL while parent is CONFIRMED (PRD-compliant).
        ll = validate_success(
            api.create_lightning_lane(
                create_lightning_lane_payload(
                    reservation_id=reservation["id"], tier="MULTI_PASS",
                ),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        assert ll["status"] == "REQUESTED"
        # Drive reservation to NO_SHOW (note: PRD §3.5 NO_SHOW cascade list
        # mentions AllergyMeal but not LightningLaneAddOn, so the LL remains
        # REQUESTED — see "Silence patterns / cross-entity-cascade" allowance).
        set_clock("2026-02-15T19:00:00Z")
        marked = validate_success(
            api.mark_no_show_reservation(
                reservation["id"], TEST_USERS["platform_admin_headers"],
            ),
            expected_status=200,
        )
        assert marked["status"] == "NO_SHOW"
        # Read current reservation version for the allocate OCC field.
        cur_res = fetch_reservation(reservation["id"], guest["id"])
        # Attempt allocate — parent is now NO_SHOW, not CONFIRMED.
        res = api.allocate_lightning_lane(
            ll["id"],
            allocate_lightning_lane_payload(cur_res["version"]),
            make_guest_headers(guest["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        # LL remains in REQUESTED.
        ll_after = fetch_lightning_lane(ll["id"], guest["id"])
        assert ll_after["status"] == "REQUESTED"

    def test_allocate_succeeds_when_reservation_is_confirmed(self, api):
        """PRD §3.7: "Allocation requires the underlying reservation to still be
        in CONFIRMED and is OCC-guarded by expected_reservation_version (see
        §2.7); a mismatch yields ERR_STALE_VERSION (HTTP 412). On commit, the
        platform computes the fee, stamps allocated_at with the commit instant,
        and sets redemption_window_end_utc to the reservation's slot_end_utc
        plus sixty minutes."

        Companion positive-path test for the same dependency: when the parent IS
        CONFIRMED, allocate transitions REQUESTED → ALLOCATED.

        Design: Difficulty/cross_entity_state_dependency/lightning_lane_allocate_requires_reservation_confirmed
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            park_code="HOLLYWOOD_STUDIOS",
            is_character_dining=False,
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        ll = validate_success(
            api.create_lightning_lane(
                create_lightning_lane_payload(
                    reservation_id=reservation["id"], tier="MULTI_PASS",
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
        assert allocated["status"] == "ALLOCATED"
