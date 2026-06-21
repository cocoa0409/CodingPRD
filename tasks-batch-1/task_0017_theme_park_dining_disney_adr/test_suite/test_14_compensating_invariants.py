"""Compensating invariants — confirm + cancel preserves DiningPlan and slot
occupancy. Queue A (Difficulty)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    setup_confirmed_reservation,
    create_pending_reservation,
    confirm_reservation,
    cancel_reservation,
    create_guest,
    create_restaurant,
    create_dining_plan,
    create_park_session,
    create_reservation_payload,
    fetch_dining_plan,
    fetch_reservation,
    list_credit_ledger_for_reservation,
    make_guest_headers,
)


# ─── DiningPlan total-credit invariance under confirm+cancel ─────────────

class TestConfirmCancelPreservesDiningPlanCredits:
    """Difficulty/compensating_invariant/confirm_then_cancel_preserves_dining_plan_total_credits"""

    def test_remaining_unchanged_held_returns_to_zero(self, api):
        """PRD §3.4: "On a successful commit, the platform sets
        Reservation.credits_held to the restaurant's dining_plan_credit_cost
        multiplied by the reservation's current party_size, increases the plan's
        table_service_credits_held by exactly that amount"
        PRD §3.4: "Cancellation from CONFIRMED requires expected_reservation_version,
        runs the OCC check, reverses the hold (decrement the plan's
        table_service_credits_held by Reservation.credits_held, zero
        Reservation.credits_held, append a CreditLedgerEntry of entry_type
        RELEASE with a credits_delta equal to the negated released quantity)"

        Design: Difficulty/compensating_invariant/confirm_then_cancel_preserves_dining_plan_total_credits
        """
        # Pre: remaining=10, held=0. After confirm: held=2. After cancel: held=0.
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            is_character_dining=True,
            park_code="EPCOT",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
            tier="DELUXE",
        )
        plan_mid = fetch_dining_plan(dp["id"], guest["id"])
        assert plan_mid["table_service_credits_held"] == 2
        assert plan_mid["table_service_credits_remaining"] == 10
        # Cancel.
        cancelled = cancel_reservation(
            reservation["id"], reservation["version"], guest["id"],
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["credits_held"] == 0
        plan_post = fetch_dining_plan(dp["id"], guest["id"])
        assert plan_post["table_service_credits_held"] == 0
        assert plan_post["table_service_credits_remaining"] == 10

    def test_credit_ledger_hold_and_release_sum_to_zero(self, api):
        """PRD §3.4: "appends a CreditLedgerEntry with entry_type HOLD and a
        positive credits_delta equal to the held quantity"
        PRD §3.4: "append a CreditLedgerEntry of entry_type RELEASE with a
        credits_delta equal to the negated released quantity"

        Companion invariant: HOLD +N and RELEASE -N must sum to zero for the
        reservation, demonstrating ledger conservation.

        Design: Difficulty/compensating_invariant/confirm_then_cancel_preserves_dining_plan_total_credits
        """
        guest, restaurant, dp, ps, reservation = setup_confirmed_reservation(
            party_size=2,
            dining_plan_credit_cost=1,
            is_character_dining=True,
            park_code="EPCOT",
            opening_local_time="08:00",
            closing_local_time="22:00",
            table_service_credits_initial=10,
            tier="DELUXE",
        )
        cancel_reservation(reservation["id"], reservation["version"], guest["id"])
        entries = list_credit_ledger_for_reservation(reservation["id"])
        # Sum of credits_delta across HOLD/RELEASE for this reservation = 0.
        total = sum(e["credits_delta"] for e in entries
                    if e["entry_type"] in ("HOLD", "RELEASE"))
        assert total == 0, f"Expected HOLD/RELEASE delta sum=0, got {total}; entries={entries}"


# ─── Restaurant slot seat occupancy preserved after cancel ───────────────

class TestConfirmCancelPreservesSlotOccupancy:
    """Difficulty/compensating_invariant/confirm_then_cancel_preserves_restaurant_slot_seat_occupancy"""

    def test_after_cancel_full_capacity_booking_succeeds(self, api):
        """PRD §3.3: "Slot capacity is enforced by summing the party_size of every
        other reservation at the same restaurant whose [slot_start_utc, slot_end_utc)
        half-open interval overlaps the candidate's interval and whose status is
        in PENDING, CONFIRMED, CHECKED_IN, or SEATED"
        PRD §3.4: "Cancellation from CONFIRMED requires expected_reservation_version,
        runs the OCC check, reverses the hold ... and cascades any
        LightningLaneAddOn for this reservation that is in REQUESTED or ALLOCATED
        to CANCELLED."

        Cancelled reservations are terminal (not in PENDING/CONFIRMED/
        CHECKED_IN/SEATED) and thus exit the capacity sum, restoring the slot's
        free-seat pool.

        Design: Difficulty/compensating_invariant/confirm_then_cancel_preserves_restaurant_slot_seat_occupancy
        """
        set_clock("2026-01-15T12:00:00Z")
        restaurant = create_restaurant(
            name="OccTest", park_code="MAGIC_KINGDOM", capacity_per_slot=4,
            opening_local_time="08:00", closing_local_time="22:00",
        )
        # Guest A: confirm + cancel party_size=2.
        guest_a = create_guest(email="occ_a@x.com")
        dp_a = create_dining_plan(guest_a["id"], table_service_credits_initial=10)
        ps_a = create_park_session(
            guest_a["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        pending_a = create_pending_reservation(
            guest_a, restaurant, ps_a, dp_a,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=2,
        )
        confirmed_a = confirm_reservation(pending_a, guest_a["id"])
        cancel_reservation(confirmed_a["id"], confirmed_a["version"], guest_a["id"])
        # Guest B: now the slot must accept a party_size=4.
        guest_b = create_guest(email="occ_b@x.com")
        dp_b = create_dining_plan(guest_b["id"], tier="DELUXE", table_service_credits_initial=10)
        ps_b = create_park_session(
            guest_b["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        payload = create_reservation_payload(
            guest_id=guest_b["id"], restaurant_id=restaurant["id"],
            park_session_id=ps_b["id"], dining_plan_id=dp_b["id"],
            slot_start_utc="2026-02-15T18:00:00Z", party_size=4,
        )
        res = api.create_reservation(payload, make_guest_headers(guest_b["id"]))
        b = validate_success(res, expected_status=201)
        assert b["status"] == "PENDING"
        assert b["party_size"] == 4

    def test_cancelled_reservation_not_counted_in_capacity_sum(self, api):
        """PRD §3.3: "Slot capacity is enforced by summing the party_size of every
        other reservation at the same restaurant whose [slot_start_utc, slot_end_utc)
        half-open interval overlaps the candidate's interval and whose status is
        in PENDING, CONFIRMED, CHECKED_IN, or SEATED"

        Companion: after cancel the reservation is in terminal CANCELLED state
        (not in the four non-terminal statuses enumerated for capacity-sum), so
        the slot is fully available for another full-capacity booking.

        Design: Difficulty/compensating_invariant/confirm_then_cancel_preserves_restaurant_slot_seat_occupancy
        """
        set_clock("2026-01-15T12:00:00Z")
        restaurant = create_restaurant(
            name="OccTest2", park_code="MAGIC_KINGDOM", capacity_per_slot=4,
            opening_local_time="08:00", closing_local_time="22:00",
        )
        guest_a = create_guest(email="occ_a2@x.com")
        dp_a = create_dining_plan(guest_a["id"], table_service_credits_initial=10)
        ps_a = create_park_session(
            guest_a["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        pending_a = create_pending_reservation(
            guest_a, restaurant, ps_a, dp_a,
            slot_start_utc="2026-02-15T18:00:00Z", party_size=2,
        )
        confirmed_a = confirm_reservation(pending_a, guest_a["id"])
        cancel_reservation(confirmed_a["id"], confirmed_a["version"], guest_a["id"])
        a_after = fetch_reservation(confirmed_a["id"], guest_a["id"])
        assert a_after["status"] == "CANCELLED"
        # Verify a fresh booking with party_size matching the full capacity is accepted.
        guest_b = create_guest(email="occ_b2@x.com")
        dp_b = create_dining_plan(guest_b["id"], tier="DELUXE", table_service_credits_initial=10)
        ps_b = create_park_session(
            guest_b["id"], park_code="MAGIC_KINGDOM", visit_date="2026-02-15",
        )
        payload = create_reservation_payload(
            guest_id=guest_b["id"], restaurant_id=restaurant["id"],
            park_session_id=ps_b["id"], dining_plan_id=dp_b["id"],
            slot_start_utc="2026-02-15T18:00:00Z", party_size=4,
        )
        b = validate_success(
            api.create_reservation(payload, make_guest_headers(guest_b["id"])),
            expected_status=201,
        )
        assert b["party_size"] == 4
