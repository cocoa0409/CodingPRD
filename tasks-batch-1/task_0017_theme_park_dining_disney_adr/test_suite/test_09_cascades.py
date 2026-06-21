"""Transitive cascade chains — ParkSession cancel → Reservation → LL; and
no-show strike → guest suspension. Queue A (Difficulty)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    setup_confirmed_reservation,
    setup_pending_reservation,
    setup_guest_restaurant_plan_session,
    create_pending_reservation,
    confirm_reservation,
    drive_guest_no_show_count,
    create_park_session,
    fetch_reservation,
    fetch_guest,
    fetch_dining_plan,
    fetch_park_session,
    fetch_lightning_lane,
    list_credit_ledger_for_reservation,
    create_lightning_lane_payload,
    make_guest_headers,
    TEST_USERS,
)


# ─── ParkSession cancel → depth-3 cascade ─────────────────────────────────

class TestParkSessionCancelDepth3Cascade:
    """Difficulty/transitive_cascade/park_session_cancel_cascades_to_reservation_then_lightning_lane_depth3"""

    def test_park_session_cancel_cascades_reservation_and_addon_and_credits(self, api):
        """PRD §3.2: "Cancelling a session is a separate path and only available
        from NOT_STARTED. When a guest cancels a NOT_STARTED session, the platform
        stamps closed_at and then runs a two-hop cascade. The first hop walks
        every Reservation whose park_session_id points at this session and whose
        status is in PENDING or CONFIRMED, flipping each to CANCELLED; for any
        reservation that was in CONFIRMED at the moment of cascade, the
        plan-credit release fires exactly as it would on a direct cancel —
        Reservation.credits_held is subtracted from the plan's
        table_service_credits_held, Reservation.credits_held is zeroed, and a
        CreditLedgerEntry of entry_type RELEASE is appended with a negative
        credits_delta."
        PRD §3.2: "The second hop is triggered by the first hop's reservation
        status changes, not by the original session cancel: for every reservation
        that was just cascade-cancelled, if a LightningLaneAddOn exists for it
        with status in REQUESTED or ALLOCATED, that add-on's status flips to
        CANCELLED as well."

        Design: Difficulty/transitive_cascade/park_session_cancel_cascades_to_reservation_then_lightning_lane_depth3
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            is_character_dining=True,
            park_code="MAGIC_KINGDOM",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        # Attach LL in REQUESTED state.
        ll = validate_success(
            api.create_lightning_lane(
                create_lightning_lane_payload(
                    reservation_id=reservation["id"], tier="SINGLE_PASS",
                ),
                make_guest_headers(guest["id"]),
            ),
            expected_status=201,
        )
        # Trigger: cancel the (still-NOT_STARTED) park session.
        cancelled_ps = validate_success(
            api.cancel_park_session(ps["id"], make_guest_headers(guest["id"])),
            expected_status=200,
        )
        assert cancelled_ps["status"] == "CANCELLED"
        # Hop 1: reservation cascade-cancelled.
        res_after = fetch_reservation(reservation["id"], guest["id"])
        assert res_after["status"] == "CANCELLED"
        # Hop 2: LL flipped to CANCELLED.
        ll_after = fetch_lightning_lane(ll["id"], guest["id"])
        assert ll_after["status"] == "CANCELLED"

    def test_park_session_cancel_releases_held_credits_and_writes_release_ledger(self, api):
        """PRD §3.2: "for any reservation that was in CONFIRMED at the moment of
        cascade, the plan-credit release fires exactly as it would on a direct
        cancel — Reservation.credits_held is subtracted from the plan's
        table_service_credits_held, Reservation.credits_held is zeroed, and a
        CreditLedgerEntry of entry_type RELEASE is appended with a negative
        credits_delta."

        Design: Difficulty/transitive_cascade/park_session_cancel_cascades_to_reservation_then_lightning_lane_depth3
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            is_character_dining=True,
            park_code="MAGIC_KINGDOM",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
        )
        # Also attach an LL to mirror the design instance setup.
        api.create_lightning_lane(
            create_lightning_lane_payload(
                reservation_id=reservation["id"], tier="SINGLE_PASS",
            ),
            make_guest_headers(guest["id"]),
        )
        api.cancel_park_session(ps["id"], make_guest_headers(guest["id"]))
        plan = fetch_dining_plan(dp["id"], guest["id"])
        assert plan["table_service_credits_held"] == 0
        assert plan["table_service_credits_remaining"] == 10
        entries = list_credit_ledger_for_reservation(reservation["id"])
        rel = [e for e in entries
               if e["entry_type"] == "RELEASE" and e["credits_delta"] == -2]
        assert len(rel) >= 1


# ─── NO_SHOW cascade → guest suspension ──────────────────────────────────

class TestNoShowFifthStrikeSuspendsGuest:
    """Difficulty/transitive_cascade/no_show_cascade_increments_strike_then_suspends_guest_depth2"""

    def test_fifth_no_show_increments_strike_to_5(self, api):
        """PRD §3.5: "Either path runs the same cascade, in this order: the
        platform increments the booking Guest.no_show_strike_count by 1"
        PRD §3.1: "A guest's status flips to SUSPENDED only as a side effect of
        accumulating no-shows (see §3.5)"

        Design: Difficulty/transitive_cascade/no_show_cascade_increments_strike_then_suspends_guest_depth2
        """
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="HOLLYWOOD_STUDIOS",
            no_show_base_fee_cents=1000,
            is_character_dining=False,
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=20,
            visit_date="2026-02-09",
        )
        # Drive 4 prior strikes.
        drive_guest_no_show_count(
            guest, restaurant, dp, num_strikes=4,
            park_code="HOLLYWOOD_STUDIOS", base_date="2026-02-10",
        )
        g_pre = fetch_guest(guest["id"])
        assert g_pre["no_show_strike_count"] == 4
        # 5th reservation triggering suspension.
        set_clock("2026-01-15T12:00:00Z")
        ps5 = create_park_session(
            guest["id"], park_code="HOLLYWOOD_STUDIOS", visit_date="2026-02-14",
        )
        pending5 = create_pending_reservation(
            guest, restaurant, ps5, dp,
            slot_start_utc="2026-02-14T18:00:00Z", party_size=1,
        )
        confirm_reservation(pending5, guest["id"])
        set_clock("2026-02-14T19:00:00Z")
        api.mark_no_show_reservation(pending5["id"], TEST_USERS["platform_admin_headers"])
        g_post = fetch_guest(guest["id"])
        assert g_post["no_show_strike_count"] == 5

    def test_fifth_no_show_suspends_guest(self, api):
        """PRD §3.1: "A guest's status flips to SUSPENDED only as a side effect of
        accumulating no-shows (see §3.5), and once suspended the guest is barred
        from creating new reservations or Lightning Lane add-ons"
        PRD §3.5: "if the post-increment count is at or above 5 the guest's
        status flips to SUSPENDED"

        Companion test to the strike-counter test, asserting the hop-2 status
        flip on the same fifth-strike trigger.

        Design: Difficulty/transitive_cascade/no_show_cascade_increments_strike_then_suspends_guest_depth2
        """
        set_clock("2026-01-15T12:00:00Z")
        guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
            park_code="HOLLYWOOD_STUDIOS",
            no_show_base_fee_cents=1000,
            is_character_dining=False,
            opening_local_time="11:00",
            closing_local_time="22:00",
            table_service_credits_initial=20,
            visit_date="2026-02-09",
        )
        drive_guest_no_show_count(
            guest, restaurant, dp, num_strikes=4,
            park_code="HOLLYWOOD_STUDIOS", base_date="2026-02-10",
        )
        set_clock("2026-01-15T12:00:00Z")
        ps5 = create_park_session(
            guest["id"], park_code="HOLLYWOOD_STUDIOS", visit_date="2026-02-14",
        )
        pending5 = create_pending_reservation(
            guest, restaurant, ps5, dp,
            slot_start_utc="2026-02-14T18:00:00Z", party_size=1,
        )
        confirm_reservation(pending5, guest["id"])
        set_clock("2026-02-14T19:00:00Z")
        api.mark_no_show_reservation(pending5["id"], TEST_USERS["platform_admin_headers"])
        g_post = fetch_guest(guest["id"])
        assert g_post["status"] == "SUSPENDED"
