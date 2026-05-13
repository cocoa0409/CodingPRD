"""Concurrency / race scenarios where the PRD explicitly defines the
guaranteed outcome.

PRD §3.3 (reservation race), PRD §3.4 (session-state race).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    create_member,
    create_reservation_payload,
    get_pile,
    get_reservation,
    make_ev_driver_headers,
    run_race,
    setup_charging_session,
    setup_ready_to_charge,
    validate_error_is_one_of,
)


# ===========================================================================
# Two members reserving the same pile (PRD §3.3)
# ===========================================================================
class TestReserveSamePileRace:
    """PRD §3.3: 'Two drivers racing for the same pile see the second
    writer rejected with ERR_PILE_ALREADY_RESERVED; first-writer-wins
    serialization on Reservation row insertion guarantees that at most
    one reservation in HELD exists per pile at any time.'"""

    def test_only_one_of_two_concurrent_reservations_succeeds(self, api):
        ctx = setup_ready_to_charge()
        m2 = create_member(
            home_operator_id=ctx["operator"]["id"],
            wallet_balance_cents=100000,
        )
        results = run_race(
            lambda: api.create_reservation(
                create_reservation_payload(pile_id=ctx["pile"]["id"]),
                make_ev_driver_headers(ctx["member"]["id"]),
            ),
            lambda: api.create_reservation(
                create_reservation_payload(pile_id=ctx["pile"]["id"]),
                make_ev_driver_headers(m2["id"]),
            ),
        )
        # PRD §3.3 names the loser explicitly:
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        # The loser must be ERR_PILE_ALREADY_RESERVED per PRD §3.3.
        body = loser.json()["data"]
        assert body["error_id"] == ApiErrorId.ERR_PILE_ALREADY_RESERVED.value


# ===========================================================================
# Stop vs abort race (PRD §3.4)
# ===========================================================================
class TestStopVsAbortRace:
    """PRD §3.4: 'When a stop and an abort race on the same session, the
    loser sees ERR_INVALID_SESSION_STATE; serialization is
    first-writer-wins on ChargingSession.status.'"""

    def test_concurrent_stop_and_abort_only_one_succeeds(self, api):
        ctx = setup_charging_session()
        # CustomerService is the actor for abort; EVDriver (member) is
        # the actor for stop. Use identity-threaded headers.
        from test_helpers import CS, make_ev_driver_headers
        results = run_race(
            lambda: api.stop_session(
                ctx["session"]["id"],
                make_ev_driver_headers(ctx["member"]["id"]),
            ),
            lambda: api.abort_session(ctx["session"]["id"], CS),
        )
        outcome = assert_race_outcome(results, 1, 1)
        loser = outcome["failures"][0]
        body = loser.json()["data"]
        assert body["error_id"] == ApiErrorId.ERR_INVALID_SESSION_STATE.value
