"""Concurrency: optimistic concurrency control, reservation overlap races,
authorization decision races.

PRD §2.4 (OCC), §2.10 (Concurrency Guarantees).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    approve_authorization_as_owner,
    assert_exactly_one_succeeds,
    create_reservation_payload,
    create_verified_user,
    make_lab_owner_headers,
    make_user_headers,
    request_authorization,
    run_race,
    setup_basic_scenario,
    setup_overlap_scenario_with_two_users,
    validate_error,
)


# ===========================================================================
# Reservation overlap race (PRD §2.10)
# ===========================================================================
class TestReservationOverlapRace:
    """PRD §2.10: 'Two User clients posting reservations on the same
    equipment with half-open intervals that intersect serialize on the
    existing-reservations overlap check; the second writer is rejected
    with ERR_RESERVATION_OVERLAP at 409.'
    """

    def test_overlapping_reservation_race_one_wins(self, api):
        """PRD §2.10: 'the second writer is rejected with
        ERR_RESERVATION_OVERLAP at 409' — exactly one of two simultaneous
        overlapping reservations succeeds."""
        s = setup_overlap_scenario_with_two_users()
        from test_helpers import cancel_reservation
        cancel_reservation(reservation=s["reservation1"], user=s["user1"])

        def op_a():
            return api.create_reservation(
                s["equipment"]["id"],
                create_reservation_payload(
                    user_id=s["user1"]["id"],
                    authorization_id=s["authorization1"]["id"],
                    start_at="2026-05-12T09:00:00.000Z",
                    end_at="2026-05-12T10:00:00.000Z",
                ),
                make_user_headers(s["user1"]["id"]),
            )

        def op_b():
            return api.create_reservation(
                s["equipment"]["id"],
                create_reservation_payload(
                    user_id=s["user2"]["id"],
                    authorization_id=s["authorization2"]["id"],
                    start_at="2026-05-12T09:30:00.000Z",
                    end_at="2026-05-12T10:30:00.000Z",
                ),
                make_user_headers(s["user2"]["id"]),
            )

        a, b = run_race(op_a, op_b)
        assert_exactly_one_succeeds(a, b)


# ===========================================================================
# Authorization decision race (PRD §2.10)
# ===========================================================================
class TestAuthorizationDecisionRace:
    """PRD §2.10: 'Two LabOwner approvals on the same PENDING_OWNER
    authorization, and the analogous race between a PlatformAdmin
    approve and a LabOwner revoke on the same authorization, both
    serialize on Authorization.status; whichever transaction commits
    second receives ERR_AUTHORIZATION_ALREADY_DECIDED at 409.'
    """

    def test_two_owner_approvals_one_wins(self, api):
        """PRD §2.10: 'serialize on Authorization.status'."""
        s = setup_basic_scenario()
        auth = request_authorization(
            equipment=s["equipment"], user=s["user"], urgency="NORMAL",
        )
        owner_h = make_lab_owner_headers(s["owner_user"]["id"])

        def op_a():
            return api.approve_authorization(auth["id"], owner_h)

        def op_b():
            return api.approve_authorization(auth["id"], owner_h)

        a, b = run_race(op_a, op_b)
        # Race produces exactly one success and one ALREADY_DECIDED loss.
        assert_exactly_one_succeeds(a, b)
