"""Charging session lifecycle: create -> start -> curve points -> stop
(SETTLED) or abort (ABORTED). PRD §3.4.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    MIN_AUTH_HOLD_CENTS,
    abort_session,
    advance_clock_to,
    append_curve_point,
    assert_charging_session,
    assert_session_terminal_zero_fees,
    create_member,
    create_reservation,
    create_session,
    emit_grid_pile_offline,
    get_pile,
    get_reservation,
    get_session,
    iso_day,
    iso_z,
    join_queue,
    run_sweep,
    setup_charging_session,
    setup_operator_station_shelved_pile,
    setup_ready_to_charge,
    setup_settled_session,
    setup_two_members_one_at_queue_front,
    start_session,
    stop_session,
    validate_error,
    validate_success,
    PO,
    make_ev_driver_headers,
)
from datetime import datetime, timedelta, timezone


# ===========================================================================
# Session create — PENDING_AUTH
# ===========================================================================
class TestSessionCreate:
    """PRD §3.4: 'A ChargingSession is created in PENDING_AUTH state by
    an EVDriver against a target pile_id.'"""

    def test_create_session_returns_pending_auth(self, api):
        ctx = setup_ready_to_charge()
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
            auth_method="APP",
        )
        assert_charging_session(session)
        assert session["status"] == "PENDING_AUTH"
        assert session["pile_id"] == ctx["pile"]["id"]
        assert session["member_id"] == ctx["member"]["id"]
        assert session["auth_method"] == "APP"


# ===========================================================================
# Session start — pile state guard
# ===========================================================================
class TestSessionStartGuards:
    """PRD §3.4: 'The pile must be in lifecycle_state ON_SHELF and
    operational_state IDLE; if not, the request is rejected with
    ERR_PILE_UNAVAILABLE.'"""

    def test_start_session_on_offline_pile_rejected(self, api):
        """PRD §3.4: 'safety takes precedence over any reservation hold,
        so a reservation that becomes invalid because the pile faulted
        between booking and arrival does not unlock charging.'"""
        ctx = setup_ready_to_charge()
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # Take the pile offline AFTER session created.
        emit_grid_pile_offline(ctx["pile"]["id"])
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PILE_UNAVAILABLE.value)

    def test_start_session_with_insufficient_wallet_rejected(self, api):
        """PRD §3.4: 'The driver's wallet_balance_cents must be at least
        one thousand cents (the minimum authentication hold); otherwise
        the start is rejected with ERR_INSUFFICIENT_BALANCE.'"""
        # Member with wallet < MIN_AUTH_HOLD_CENTS.
        ctx = setup_ready_to_charge(member_wallet_cents=500)
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


# ===========================================================================
# Reservation-backed start
# ===========================================================================
class TestReservationBackedStart:
    """PRD §3.4: 'If a reservation_id was supplied, the reservation must
    be in HELD status, now must be strictly less than its
    hold_expires_at, the reservation's member_id must match the
    session's member_id, and its pile_id must match the session's
    pile_id — a mismatch on member or pile yields
    ERR_RESERVATION_MISMATCH.'"""

    def test_reservation_mismatch_on_member_rejected(self, api):
        ctx = setup_ready_to_charge()
        # Reservation belongs to member A.
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        # Session claims member B.
        member_b = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        from test_helpers import create_session_payload
        res = api.create_session(
            create_session_payload(
                pile_id=ctx["pile"]["id"],
                member_id=member_b["id"],
                auth_method="APP",
                reservation_id=reservation["id"],
            ),
            make_ev_driver_headers(member_b["id"]),
        )
        # The mismatch may surface at /sessions create or at /start;
        # PRD §3.4 wording covers 'POST /sessions, POST /sessions/{id}/start'
        # in the scaffold validation. We accept either point, but the
        # error_id must be ERR_RESERVATION_MISMATCH.
        validate_error(res, ApiErrorId.ERR_RESERVATION_MISMATCH.value)

    def test_reservation_expired_at_start_rejected(self, api):
        """PRD §3.4: 'an expired hold yields ERR_RESERVATION_EXPIRED.'"""
        ctx = setup_ready_to_charge()
        base = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
        advance_clock_to(iso_z(base))
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
            reservation_id=reservation["id"],
        )
        # Advance well past the 15-minute hold without running sweep.
        advance_clock_to(iso_z(base + timedelta(minutes=20)))
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["member"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESERVATION_EXPIRED.value)

    def test_reservation_backed_start_transitions_reservation_to_activated(
        self, api,
    ):
        """PRD §3.4: 'If the session was reservation-backed, the
        reservation transitions from HELD to ACTIVATED.'"""
        ctx = setup_ready_to_charge()
        reservation = create_reservation(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
            reservation_id=reservation["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert session["status"] == "CHARGING"
        r = get_reservation(reservation["id"])
        assert r["status"] == "ACTIVATED"


# ===========================================================================
# Queue-jumping prevention
# ===========================================================================
class TestQueueJumpingPrevention:
    """PRD §3.4: 'If no reservation_id was supplied, either there must
    be no WAITING queue entry at the pile's station, or the driver must
    be the holder of the WAITING entry at position one — otherwise the
    start is rejected with ERR_QUEUE_NOT_AT_FRONT.'"""

    def test_start_without_reservation_when_other_member_is_front_rejected(
        self, api,
    ):
        ctx = setup_two_members_one_at_queue_front()
        # m_late is at position 2.
        from test_helpers import create_session_payload
        # m_late attempts unreserved start.
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["m_late"]["id"],
        )
        res = api.start_session(
            session["id"],
            make_ev_driver_headers(ctx["m_late"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_QUEUE_NOT_AT_FRONT.value)

    def test_start_without_reservation_on_empty_queue_succeeds(self, api):
        """PRD §3.4: 'either there must be no WAITING queue entry at the
        pile's station ... or [position one]'."""
        ctx = setup_ready_to_charge()
        # No one in queue.
        session = create_session(
            pile_id=ctx["pile"]["id"], member_id=ctx["member"]["id"],
        )
        session = start_session(
            session_id=session["id"], member_id=ctx["member"]["id"],
        )
        assert session["status"] == "CHARGING"


# ===========================================================================
# Session start — pile becomes IN_USE
# ===========================================================================
class TestSessionStartSideEffects:
    """PRD §3.4: 'The pile's operational_state is set to IN_USE.'"""

    def test_start_sets_pile_in_use_and_session_started_at(self, api):
        ctx = setup_charging_session()
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "IN_USE"
        # PRD §3.4: 'The session's started_at is set to now.'
        assert ctx["session"]["started_at"] is not None


# ===========================================================================
# Curve point validation (monotonicity)
# ===========================================================================
class TestCurvePointMonotonicity:
    """PRD §3.4: 'Any append violating monotonicity on
    cumulative_energy_milli or strict-increase on sampled_at is rejected
    with ERR_CURVE_NON_MONOTONIC.'"""

    def test_decreasing_cumulative_energy_rejected(self, api):
        ctx = setup_charging_session()
        from test_helpers import create_curve_point_payload
        # First point: 10000 milli at t1.
        api.create_curve_point(
            ctx["session"]["id"],
            create_curve_point_payload(
                sampled_at="2026-05-13T00:01:00.000Z",
                instant_power_kw=60.0,
                cumulative_energy_milli=10000,
                window_tag="FLAT",
            ),
            PO,
        )
        # Second point: lower cumulative — should reject.
        res = api.create_curve_point(
            ctx["session"]["id"],
            create_curve_point_payload(
                sampled_at="2026-05-13T00:02:00.000Z",
                instant_power_kw=60.0,
                cumulative_energy_milli=9000,
                window_tag="FLAT",
            ),
            PO,
        )
        validate_error(res, ApiErrorId.ERR_CURVE_NON_MONOTONIC.value)

    def test_non_increasing_sampled_at_rejected(self, api):
        """PRD §3.4: 'sampled_at (strictly increasing per session)'."""
        ctx = setup_charging_session()
        from test_helpers import create_curve_point_payload
        api.create_curve_point(
            ctx["session"]["id"],
            create_curve_point_payload(
                sampled_at="2026-05-13T00:01:00.000Z",
                instant_power_kw=60.0,
                cumulative_energy_milli=10000,
                window_tag="FLAT",
            ),
            PO,
        )
        # Equal-or-earlier sampled_at — must reject.
        res = api.create_curve_point(
            ctx["session"]["id"],
            create_curve_point_payload(
                sampled_at="2026-05-13T00:01:00.000Z",
                instant_power_kw=60.0,
                cumulative_energy_milli=11000,
                window_tag="FLAT",
            ),
            PO,
        )
        validate_error(res, ApiErrorId.ERR_CURVE_NON_MONOTONIC.value)


# ===========================================================================
# Stop -> SETTLING -> SETTLED
# ===========================================================================
class TestSessionStopAndSettle:
    """PRD §3.4: 'The driver (or the platform) stops the session,
    advancing it from CHARGING to SETTLING ... Once at least one curve
    point with non-negative cumulative_energy_milli exists, the session
    automatically advances from SETTLING to SETTLED.'"""

    def test_stop_session_advances_to_settled(self, api):
        ctx = setup_settled_session()
        session = ctx["session"]
        assert session["status"] == "SETTLED"
        assert session["ended_at"] is not None

    def test_pile_returns_to_idle_after_settle(self, api):
        """PRD §3.4: 'Simultaneously, the pile returns from IN_USE to
        IDLE.'"""
        ctx = setup_settled_session()
        pile = get_pile(ctx["pile"]["id"])
        assert pile["operational_state"] == "IDLE"


# ===========================================================================
# Abort path (CHARGING -> ABORTED, zero fees)
# ===========================================================================
class TestSessionAbort:
    """PRD §3.4: 'CustomerService may invoke an override abort, which
    produces the same effects — no fees, total of zero, an audit row.'"""

    def test_customer_service_abort_sets_zero_fees_and_aborted_status(
        self, api,
    ):
        ctx = setup_charging_session()
        aborted = abort_session(session_id=ctx["session"]["id"])
        assert_session_terminal_zero_fees(aborted)
