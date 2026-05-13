"""Reservation lifecycle and walk-up queue.

PRD §3.3 (Reservations, Queues, and the Path to Charging).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NO_SHOW_BASE_PENALTY_CENTS,
    NO_SHOW_MAX_PENALTY_CENTS,
    MAX_STRIKES_FOR_RESERVATION,
    assert_queue_entry,
    assert_reservation,
    abandon_queue_entry,
    advance_clock_to,
    cancel_reservation,
    create_member,
    create_reservation,
    create_pricing_version,
    create_session,
    emit_grid_pile_offline,
    get_member,
    get_reservation,
    iso_day,
    iso_z,
    join_queue,
    list_queue_entries,
    no_show_penalty_for_prior_strikes,
    run_sweep,
    setup_operator_station_pile_off_shelf,
    setup_operator_station_shelved_pile,
    setup_ready_to_charge,
    setup_reservation_held,
    setup_strike_member,
    setup_two_members_one_at_queue_front,
    start_session,
    validate_error,
    validate_success,
    PO,
    make_ev_driver_headers,
)
from datetime import datetime, timedelta, timezone


# ===========================================================================
# Reservation create — pile availability
# ===========================================================================
class TestReservationCreate:
    """PRD §3.3: 'A reservation may only be created when the pile is fit
    to serve — that is, the pile's lifecycle_state is ON_SHELF and
    operational_state is IDLE; if either is otherwise (FAULT, OFFLINE,
    or any non-ON_SHELF lifecycle), the request is rejected with
    ERR_PILE_UNAVAILABLE.'"""

    def test_reservation_on_idle_pile_succeeds_with_status_held(self, api):
        """PRD §3.3: 'sets status to HELD'."""
        ctx = setup_ready_to_charge()
        res = api.create_reservation(
            {"pile_id": ctx["pile"]["id"]},
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        body = validate_success(res, expected_status=201)
        assert_reservation(body)
        assert body["status"] == "HELD"
        assert body["pile_id"] == ctx["pile"]["id"]
        assert body["member_id"] == ctx["member"]["id"]

    def test_reservation_on_off_shelf_pile_rejected_pile_unavailable(
        self, api,
    ):
        """PRD §3.3: 'if either is otherwise (... or any non-ON_SHELF
        lifecycle), the request is rejected with
        ERR_PILE_UNAVAILABLE.'"""
        ctx = setup_operator_station_pile_off_shelf()
        # Member belongs to the platform operator.
        member = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        res = api.create_reservation(
            {"pile_id": ctx["pile"]["id"]},
            make_ev_driver_headers(member["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_UNAVAILABLE.value)

    def test_reservation_on_offline_pile_rejected_pile_unavailable(
        self, api,
    ):
        """PRD §3.3: 'if either is otherwise (FAULT, OFFLINE ...), the
        request is rejected with ERR_PILE_UNAVAILABLE.'"""
        ctx = setup_ready_to_charge()
        # Send pile OFFLINE before any reservation.
        emit_grid_pile_offline(ctx["pile"]["id"])
        res = api.create_reservation(
            {"pile_id": ctx["pile"]["id"]},
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_UNAVAILABLE.value)


# ===========================================================================
# Reservation already-reserved
# ===========================================================================
class TestReservationAlreadyReserved:
    """PRD §3.3: 'Two drivers racing for the same pile see the second
    writer rejected with ERR_PILE_ALREADY_RESERVED; first-writer-wins
    serialization on Reservation row insertion guarantees that at most
    one reservation in HELD exists per pile at any time.'"""

    def test_second_reservation_on_same_held_pile_rejected(self, api):
        ctx = setup_ready_to_charge()
        # First reservation succeeds.
        create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # A second member tries while the first is still HELD.
        m2 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        res = api.create_reservation(
            {"pile_id": ctx["pile"]["id"]},
            make_ev_driver_headers(m2["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_ALREADY_RESERVED.value)


# ===========================================================================
# Reservation cancel (HELD -> CANCELLED, no strike)
# ===========================================================================
class TestReservationCancel:
    """PRD §3.3: 'Drivers cancel a HELD reservation through the cancel
    action; this is the only path to CANCELLED that does not incur a
    strike.'"""

    def test_cancel_held_reservation_moves_to_cancelled(self, api):
        ctx = setup_reservation_held()
        cancelled = cancel_reservation(
            reservation_id=ctx["reservation"]["id"],
            member_id=ctx["member"]["id"],
        )
        assert cancelled["status"] == "CANCELLED"

    def test_cancel_does_not_increment_no_show_strikes(self, api):
        """PRD §3.3: 'this is the only path to CANCELLED that does not
        incur a strike.'"""
        ctx = setup_reservation_held()
        cancel_reservation(
            reservation_id=ctx["reservation"]["id"],
            member_id=ctx["member"]["id"],
        )
        m = get_member(ctx["member"]["id"])
        assert m["no_show_strikes"] == 0


# ===========================================================================
# Reservation expiry via sweep (HELD -> EXPIRED)
# ===========================================================================
class TestReservationSweepExpiry:
    """PRD §3.3: 'A HELD reservation transitions to EXPIRED automatically
    when the sweep capability is invoked at an instant where now is at
    or after hold_expires_at.'"""

    def test_sweep_after_hold_expiry_marks_reservation_expired(self, api):
        ctx = setup_ready_to_charge()
        # Start clock at a known base.
        base = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        advance_clock_to(iso_z(base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # Advance well past the 15-minute hold.
        advance_clock_to(iso_z(base + timedelta(minutes=20)))
        run_sweep()
        r = get_reservation(reservation["id"])
        assert r["status"] == "EXPIRED"

    def test_first_expiry_increments_strikes_and_charges_base_penalty(
        self, api,
    ):
        """PRD §3.3: 'a driver expiring their first reservation (zero
        prior strikes) is therefore charged five hundred cents.'"""
        ctx = setup_ready_to_charge()
        base = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        advance_clock_to(iso_z(base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        advance_clock_to(iso_z(base + timedelta(minutes=20)))
        run_sweep()
        r = get_reservation(reservation["id"])
        m = get_member(ctx["member"]["id"])
        assert m["no_show_strikes"] == 1
        assert r["no_show_penalty_cents"] == NO_SHOW_BASE_PENALTY_CENTS
        # PRD §3.3: 'subtracts that penalty from wallet_balance_cents.'
        assert m["wallet_balance_cents"] == 100000 - NO_SHOW_BASE_PENALTY_CENTS


# ===========================================================================
# No-show strike threshold
# ===========================================================================
class TestNoShowStrikeThreshold:
    """PRD §3.3: 'A driver whose no_show_strikes has reached three or
    more is barred from reserving — the request is rejected with
    ERR_NO_SHOW_THRESHOLD_EXCEEDED.'"""

    def test_member_with_three_strikes_cannot_make_new_reservation(
        self, api,
    ):
        ctx = setup_strike_member(target_strikes=3)
        # Now try a new reservation on a fresh pile.
        # Member already has 3 strikes.
        assert ctx["member"]["no_show_strikes"] == 3
        res = api.create_reservation(
            {"pile_id": ctx["pile"]["id"]},
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(
            res, ApiErrorId.ERR_NO_SHOW_THRESHOLD_EXCEEDED.value,
        )


# ===========================================================================
# No-show penalty saturation (PRD §3.3)
# ===========================================================================
class TestNoShowPenaltySaturation:
    """PRD §3.3: 'a second expiry (one prior strike) is one thousand
    cents; a third (two prior strikes) is two thousand cents; a fourth
    and beyond saturate at the five-thousand-cent ceiling because
    doubling from two thousand would exceed it.'"""

    def test_first_expiry_penalty_500_cents(self, api):
        """PRD §3.3: 'a driver expiring their first reservation (zero
        prior strikes) is therefore charged five hundred cents.'"""
        # 2030 is far enough in the future that any preceding test
        # leaves the clock earlier; advance is forward-only here.
        clock_base = datetime(2030, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ctx = setup_strike_member(
            target_strikes=0, clock_base=clock_base,
        )
        advance_clock_to(iso_z(clock_base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        advance_clock_to(iso_z(clock_base + timedelta(minutes=20)))
        run_sweep()
        r = get_reservation(reservation["id"])
        assert r["no_show_penalty_cents"] == 500

    def test_second_expiry_penalty_1000_cents(self, api):
        """PRD §3.3: 'a second expiry (one prior strike) is one
        thousand cents.'"""
        clock_base = datetime(2031, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ctx = setup_strike_member(
            target_strikes=1, clock_base=clock_base,
        )
        # Cycle 0 ran at clock_base + 0..16 min; advance further.
        trigger_base = clock_base + timedelta(hours=4)
        advance_clock_to(iso_z(trigger_base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        advance_clock_to(iso_z(trigger_base + timedelta(minutes=20)))
        run_sweep()
        r = get_reservation(reservation["id"])
        assert r["no_show_penalty_cents"] == 1000

    def test_third_expiry_penalty_2000_cents(self, api):
        """PRD §3.3: 'a third (two prior strikes) is two thousand
        cents.'"""
        clock_base = datetime(2032, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ctx = setup_strike_member(
            target_strikes=2, clock_base=clock_base,
        )
        trigger_base = clock_base + timedelta(hours=6)
        advance_clock_to(iso_z(trigger_base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        advance_clock_to(iso_z(trigger_base + timedelta(minutes=20)))
        run_sweep()
        r = get_reservation(reservation["id"])
        assert r["no_show_penalty_cents"] == 2000



# ===========================================================================
# Queue join / abandon / re-rank
# ===========================================================================
class TestQueueJoinAndPosition:
    """PRD §3.3: 'A QueueEntry is created against a station_id with
    member_id taken from X-User-ID; ... position is assigned as one plus
    the maximum position of any WAITING entry at the station, or one if
    the queue is empty.'"""

    def test_first_queue_entry_gets_position_one(self, api):
        ctx = setup_operator_station_shelved_pile()
        member = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        q = join_queue(
            station_id=ctx["station"]["id"], member_id=member["id"],
        )
        assert_queue_entry(q)
        assert q["status"] == "WAITING"
        assert q["position"] == 1

    def test_second_queue_entry_gets_position_two(self, api):
        ctx = setup_operator_station_shelved_pile()
        m1 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        m2 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        join_queue(station_id=ctx["station"]["id"], member_id=m1["id"])
        q2 = join_queue(
            station_id=ctx["station"]["id"], member_id=m2["id"],
        )
        assert q2["position"] == 2

    def test_abandon_decrements_later_positions(self, api):
        """PRD §3.3: 'their entry moves to ABANDONED and every WAITING
        entry at the same station whose position is greater than the
        abandoning entry's position decrements by one.'"""
        ctx = setup_operator_station_shelved_pile()
        m1 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        m2 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        m3 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        q1 = join_queue(
            station_id=ctx["station"]["id"], member_id=m1["id"],
        )
        q2 = join_queue(
            station_id=ctx["station"]["id"], member_id=m2["id"],
        )
        q3 = join_queue(
            station_id=ctx["station"]["id"], member_id=m3["id"],
        )
        # Abandon the middle entry.
        abandon_queue_entry(
            queue_entry_id=q2["id"], member_id=m2["id"],
        )
        rows = list_queue_entries(
            ctx["station"]["id"], params={"limit": 100, "status": "WAITING"},
        )
        # q1 should remain position 1; q3 should now be position 2.
        positions_by_id = {r["id"]: r["position"] for r in rows}
        assert positions_by_id.get(q1["id"]) == 1
        assert positions_by_id.get(q3["id"]) == 2
        # The abandoned entry is no longer WAITING.
        # We could also check the abandoned entry's status by fetching
        # the list with status filter unspecified, but the WAITING-only
        # response above is sufficient.
