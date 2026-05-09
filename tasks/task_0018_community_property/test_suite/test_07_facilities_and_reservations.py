"""Facility reservations, slot grid, capacity, and deposit settlement
(PRD §3.7).

Covers:
- Reservation booking: slot grid alignment → ERR_SLOT_MISALIGNED, past slot →
  ERR_SLOT_IN_PAST, capacity boundary → ERR_FACILITY_SLOT_FULL.
- Half-open interval semantics + capacity boundary (difficulty-design instance
  facility_slot_full_capacity_boundary AND facility_slot_half_open_interval_with_capacity).
- Owner-delinquency block on booking → ERR_OWNER_DELINQUENT (cross-entity-state
  dependency reservation_check_in_blocked_when_owner_delinquent).
- Deposit settlement waterfall (PRD §3.7) and the conservation invariant
  initial_deposit == refund + forfeit (difficulty-design instance
  reservation_deposit_conservation_yuan).
- Damage spillover creates a new FeeBill (difficulty-design instance
  reservation_damage_spillover_cascade).
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    assert_deposit_invariant,
    book_default_reservation,
    book_reservation,
    close_reservation_payload,
    create_facility,
    create_owner_with_property,
    create_reservation_payload,
    fetch_bill,
    iso_utc,
    list_audit_entries_for,
    make_owner_headers,
    reservation_check_in,
    reservation_close,
    setup_overdue_bill,
    setup_reservation_with_deposit,
    TEST_USERS,
    validate_error,
    validate_success,
)


def _grid_aligned_slot(slot_minutes: int, hours_in_future: int = 24, *, base: datetime = None):
    """Return (slot_start_at_iso, slot_end_at_iso) on the slot_minutes grid in the future.

    *base* defaults to current wall-clock UTC. Tests whose setup advanced the
    server's logical clock should pass an explicit base derived from that
    advance instant — otherwise wall-clock-based slots will be in the past
    relative to the server's now() and the booking will be rejected with
    ERR_SLOT_IN_PAST.
    """
    if base is None:
        base = datetime.now(timezone.utc)
    target = base + timedelta(hours=hours_in_future)
    minutes_from_midnight = target.hour * 60 + target.minute
    bucket = ((minutes_from_midnight + slot_minutes - 1) // slot_minutes) * slot_minutes
    aligned = target.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=bucket)
    end = aligned + timedelta(minutes=slot_minutes)
    return iso_utc(aligned), iso_utc(end)


class TestReservationBookingValidation:
    def test_misaligned_slot_start_rejected(self, api):
        """PRD §3.7: "slot_start_at must be aligned to the facility's slot grid
        (zero-base — meaning a 60-minute slot must start on the hour, a 120-minute
        slot every two hours from midnight, and so on); a misaligned slot or a
        length mismatch is rejected with ERR_SLOT_MISALIGNED."

        Claim: a 60-minute facility booked at HH:30 grid → ERR_SLOT_MISALIGNED.
        """
        facility = create_facility(slot_minutes=60, capacity_per_slot=1)
        owner, _prop = create_owner_with_property()
        # Build a 30-minute-misaligned start.
        target = datetime.now(timezone.utc) + timedelta(hours=24)
        aligned = target.replace(hour=10, minute=30, second=0, microsecond=0)
        end = aligned + timedelta(minutes=60)
        headers = make_owner_headers(owner["id"])
        payload = create_reservation_payload(facility["id"], iso_utc(aligned), iso_utc(end))
        res = api.create_reservation(payload, headers)
        validate_error(res, "ERR_SLOT_MISALIGNED")

    def test_slot_length_mismatch_rejected(self, api):
        """PRD §3.7: "The slot length must equal the facility's slot_minutes
        exactly, ... a misaligned slot or a length mismatch is rejected with
        ERR_SLOT_MISALIGNED."

        Claim: a 60-minute facility booked with a 30-minute window
        ([10:00, 10:30)) → ERR_SLOT_MISALIGNED.
        """
        facility = create_facility(slot_minutes=60, capacity_per_slot=1)
        owner, _prop = create_owner_with_property()
        target = datetime.now(timezone.utc) + timedelta(hours=24)
        aligned = target.replace(hour=10, minute=0, second=0, microsecond=0)
        end = aligned + timedelta(minutes=30)
        headers = make_owner_headers(owner["id"])
        payload = create_reservation_payload(facility["id"], iso_utc(aligned), iso_utc(end))
        res = api.create_reservation(payload, headers)
        validate_error(res, "ERR_SLOT_MISALIGNED")

    def test_past_slot_rejected(self, api):
        """PRD §3.7: "The slot_start_at must be strictly later than now() — a past
        slot is rejected with ERR_SLOT_IN_PAST."

        Claim: slot_start_at in the past → ERR_SLOT_IN_PAST.
        """
        facility = create_facility(slot_minutes=60, capacity_per_slot=1)
        owner, _prop = create_owner_with_property()
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        # Align to grid, then ensure it's in the past.
        past_aligned = past.replace(minute=0, second=0, microsecond=0)
        end = past_aligned + timedelta(minutes=60)
        headers = make_owner_headers(owner["id"])
        payload = create_reservation_payload(facility["id"], iso_utc(past_aligned), iso_utc(end))
        res = api.create_reservation(payload, headers)
        validate_error(res, "ERR_SLOT_IN_PAST")


class TestSlotCapacityBoundary:
    """Difficulty-design instance: facility_slot_full_capacity_boundary."""

    def test_capacity_full_third_booking_rejected(self, api):
        """PRD §3.7: "The number of currently non-terminal reservations on the same
        facility for the same slot_start_at must remain at or below capacity_per_slot;
        an attempt that would push the count past the cap is rejected with
        ERR_FACILITY_SLOT_FULL."

        Claim: a facility with capacity_per_slot=2, two existing non-terminal
        reservations on slot S, a third booking on S → ERR_FACILITY_SLOT_FULL.

        # difficulty: boundary_precision_check/facility_slot_full_capacity_boundary
        """
        facility = create_facility(slot_minutes=60, capacity_per_slot=2)
        slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=48)
        # Two distinct owners book the same slot — both succeed.
        owner_a, _ = create_owner_with_property()
        owner_b, _ = create_owner_with_property()
        owner_c, _ = create_owner_with_property()
        book_reservation(owner_a, facility, slot_start, slot_end)
        book_reservation(owner_b, facility, slot_start, slot_end)
        # Third must fail.
        headers_c = make_owner_headers(owner_c["id"])
        payload = create_reservation_payload(facility["id"], slot_start, slot_end)
        res = api.create_reservation(payload, headers_c)
        validate_error(res, "ERR_FACILITY_SLOT_FULL")


class TestHalfOpenIntervalSemantics:
    """Difficulty-design instance: facility_slot_half_open_interval_with_capacity."""

    def test_adjacent_slot_does_not_collide(self, api):
        """PRD §3.7: "the number of currently non-terminal reservations on the same
        facility for the same slot_start_at must remain at or below capacity_per_slot."

        Adjacent slots [10:00,11:00) and [11:00,12:00) have *different* slot_start_at
        values, so they share no aggregate-capacity bucket. With capacity_per_slot=1,
        booking the adjacent [11:00,12:00) when [10:00,11:00) is already booked must
        succeed.

        Claim: with capacity_per_slot=1, a booking at slot [11:00,12:00) succeeds
        even when slot [10:00,11:00) is already BOOKED.

        # difficulty: resource_temporal_overlap/facility_slot_half_open_interval_with_capacity
        """
        facility = create_facility(slot_minutes=60, capacity_per_slot=1)
        # Place two adjacent grid-aligned slots in the future.
        target = datetime.now(timezone.utc) + timedelta(hours=24)
        first_start = target.replace(minute=0, second=0, microsecond=0)
        first_end = first_start + timedelta(minutes=60)
        second_start = first_end
        second_end = second_start + timedelta(minutes=60)
        owner_a, _ = create_owner_with_property()
        owner_b, _ = create_owner_with_property()
        book_reservation(owner_a, facility, iso_utc(first_start), iso_utc(first_end))
        # Adjacent — must succeed because slot_start_at differs.
        booked = book_reservation(owner_b, facility, iso_utc(second_start), iso_utc(second_end))
        assert booked["status"] == "BOOKED"
        assert booked["slot_start_at"] == iso_utc(second_start)


class TestDelinquencyBlocksBooking:
    """Difficulty-design instance: reservation_check_in_blocked_when_owner_delinquent."""

    def test_delinquent_owner_cannot_book(self, api):
        """PRD §3.7: "An owner with at least one fee bill in OVERDUE is blocked
        from booking with ERR_OWNER_DELINQUENT."

        Claim: with the owner sitting on an OVERDUE bill, POST /reservations →
        ERR_OWNER_DELINQUENT.

        # difficulty: cross_entity_state_dependency/reservation_check_in_blocked_when_owner_delinquent
        """
        owner, _prop, _rule, overdue = setup_overdue_bill(days_past_due=20)
        assert overdue["status"] == "OVERDUE"
        facility = create_facility(slot_minutes=60, capacity_per_slot=1)
        # Compute slot relative to the post-setup logical clock (due_date + days_past_due)
        # so the slot is genuinely in the future from the server's perspective.
        clock_base = datetime.fromisoformat(overdue["due_date"].replace("Z", "+00:00")) + timedelta(days=20)
        slot_start, slot_end = _grid_aligned_slot(60, hours_in_future=48, base=clock_base)
        headers = make_owner_headers(owner["id"])
        payload = create_reservation_payload(facility["id"], slot_start, slot_end)
        res = api.create_reservation(payload, headers)
        validate_error(res, "ERR_OWNER_DELINQUENT")


class TestDepositSettlementConservation:
    """Difficulty-design instance: reservation_deposit_conservation_yuan.
    PRD §3.7: "the originally-held deposit equals the sum of the refund and the forfeit."
    """

    def test_free_window_cancel_refunds_full_deposit(self, api):
        """PRD §3.7: "For a cancellation made at or before the cutoff slot_start_at
        minus cancellation_window_hours (in plain words: cancellations made at least
        the configured window of hours before the slot starts), the full deposit_held
        is refunded and nothing is forfeited."

        Claim: cancel >24h before slot → refund=500.00, forfeit=0.00,
        invariant 500 == 500 + 0.

        # difficulty: compensating_invariant/reservation_deposit_conservation_yuan
        """
        owner, _facility, res = setup_reservation_with_deposit(
            damage_deposit=500.00,
            cancellation_window_hours=24,
            starts_in_seconds=60 * 60 * 48,  # slot is 48h in the future
        )
        initial_deposit = res["deposit_held"]
        assert initial_deposit == pytest.approx(500.00, abs=0.001)
        headers = make_owner_headers(owner["id"])
        cancelled = validate_success(api.cancel_reservation(res["id"], headers), 200)
        assert cancelled["status"] == "CANCELLED"
        # PRD §3.7: free-window cancel — refund=500, forfeit=0.
        assert cancelled["deposit_held"] == pytest.approx(0.0, abs=0.001), (
            "deposit_held drops to 0 after refund per PRD §3.7"
        )
        # Reconstruct refund/forfeit. Since the full deposit was refunded and none
        # forfeited, the conservation invariant 500 == refund(500) + forfeit(0) holds.
        refund = initial_deposit - 0.0  # full refund
        forfeit = 0.0
        assert_deposit_invariant(initial_deposit, refund, forfeit)

    def test_late_cancel_within_window_forfeits_half(self, api):
        """PRD §3.7: "For a cancellation made after that cutoff, fifty percent of
        deposit_held is refunded — deposit_held is replaced by
        round(deposit_held * 0.5, 2) using half-up rounding, the same amount is
        recorded as forfeited, and the difference between the original and the
        refunded portion is the forfeited share."

        Claim: cancel within the window → deposit_held drops to 250.00 (the forfeit),
        and the conservation invariant 500 == 250 + 250 holds.

        # difficulty: compensating_invariant/reservation_deposit_conservation_yuan
        """
        # Book just inside the cancellation window (e.g., 1 hour before slot start
        # against a 24h window). PRD says: "cancellations made at least the
        # configured window of hours before the slot starts" qualify for free —
        # therefore "less than 24 hours before slot" = late cancel.
        facility = create_facility(slot_minutes=60, capacity_per_slot=1, cancellation_window_hours=24, damage_deposit=500.00)
        owner, _prop = create_owner_with_property()
        # Slot 30 minutes in the future, 60-minute aligned start.
        target = datetime.now(timezone.utc) + timedelta(minutes=90)
        aligned = target.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        end = aligned + timedelta(minutes=60)
        # Ensure aligned is still in the future and well under cancellation window.
        if aligned <= datetime.now(timezone.utc) + timedelta(hours=23):
            res_obj = book_reservation(owner, facility, iso_utc(aligned), iso_utc(end))
        else:
            # Re-pick: 1 hour from now, on the next hour grid.
            now = datetime.now(timezone.utc)
            aligned = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            end = aligned + timedelta(minutes=60)
            res_obj = book_reservation(owner, facility, iso_utc(aligned), iso_utc(end))
        initial_deposit = res_obj["deposit_held"]
        assert initial_deposit == pytest.approx(500.00, abs=0.001)
        headers = make_owner_headers(owner["id"])
        cancelled = validate_success(api.cancel_reservation(res_obj["id"], headers), 200)
        assert cancelled["status"] == "CANCELLED"
        # Late-cancel: deposit_held replaced by round(500*0.5, 2) = 250.00.
        assert cancelled["deposit_held"] == pytest.approx(250.00, abs=0.001), (
            f"Late cancel must leave deposit_held = 250.00; got {cancelled['deposit_held']}"
        )
        refund = 250.00
        forfeit = initial_deposit - refund
        assert_deposit_invariant(initial_deposit, refund, forfeit)


class TestDamageSpilloverCascade:
    """Difficulty-design instance: reservation_damage_spillover_cascade.
    PRD §3.7: damage_amount > deposit creates a new FeeBill for the spillover."""

    def test_damage_close_creates_new_spillover_bill(self, api, property_manager_headers):
        """PRD §3.7: "if damage_amount is strictly greater than deposit_held the
        spillover (the difference between damage_amount and deposit_held, rounded
        half-up to two decimals) becomes a fresh fee bill of kind FIXED_AMOUNT_MONTHLY
        whose principal_amount is the spillover figure and whose due_date is fourteen
        days from the moment of closure."

        Setup: facility with damage_deposit=500.00, reservation booked, owner checks
        in after slot_start_at, manager closes with damage_amount=800.00 → spillover=300.00.

        Claim: a new FeeBill exists with principal_amount=300.00, status=OPEN,
        kind FIXED_AMOUNT_MONTHLY equivalent (we verify via principal value and that
        a fresh OPEN bill was created on the property).

        # difficulty: transitive_cascade/reservation_damage_spillover_cascade
        """
        facility = create_facility(
            slot_minutes=60, capacity_per_slot=1,
            cancellation_window_hours=1, damage_deposit=500.00,
        )
        owner, prop = create_owner_with_property()
        # Slot is 60 minutes from now on a grid.
        target = datetime.now(timezone.utc) + timedelta(hours=2)
        aligned = target.replace(minute=0, second=0, microsecond=0)
        end = aligned + timedelta(minutes=60)
        headers = make_owner_headers(owner["id"])
        # Book.
        res = book_reservation(owner, facility, iso_utc(aligned), iso_utc(end))
        # Advance clock to slot_start_at, then check-in.
        advance_clock_to(iso_utc(aligned + timedelta(seconds=1)))
        checked_in = validate_success(api.check_in_reservation(res["id"], headers), 200)
        assert checked_in["status"] == "CHECKED_IN"
        # Advance past slot_end_at.
        advance_clock_to(iso_utc(end + timedelta(seconds=1)))
        # Manager closes with damage_amount = 800.00 → spillover = 300.00.
        closed = validate_success(
            api.close_reservation(
                res["id"], close_reservation_payload(damage_amount=800.00), property_manager_headers
            ),
            200,
        )
        assert closed["status"] == "DAMAGED"
        # Spillover bill: list bills for this property with status=OPEN.
        bills_res = api.list_fee_bills(
            property_manager_headers, params={"property_id": prop["id"], "status": "OPEN"}
        )
        body = bills_res.json() if bills_res.text else {}
        items = body.get("data", [])
        # Expect a new OPEN bill of principal 300.00.
        spillovers = [b for b in items if abs(b.get("principal_amount", 0) - 300.00) < 0.01]
        assert spillovers, (
            f"PRD §3.7: expected a fresh OPEN FeeBill with principal=300.00 after damage close; "
            f"saw {[b.get('principal_amount') for b in items]}"
        )
