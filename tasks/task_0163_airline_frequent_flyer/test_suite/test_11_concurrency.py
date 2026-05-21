"""Concurrency-defined races — PRD §2.11.

Every loser code below is named verbatim in PRD prose. Tests use
assert_race_outcome / validate_error_is_one_of since timing of the race
admits either ordering — but the LOSER error_id is pinned by PRD for
each scenario.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_exactly_one_succeeds,
    create_award_booking_payload,
    create_flight,
    create_gift_payload,
    create_member,
    create_member_with_balance,
    fill_flight_first_inventory_to_zero,
    make_member_headers,
    points_adjustment_payload,
    run_race,
    setup_held_award_booking,
    setup_load_factor_band,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestFlightCancelRaceWithConfirm:

    def test_cancel_wins_race_with_confirm(self, api, admin_headers):
        """PRD §2.11: "When a member confirms an AwardBooking while an
        administrator concurrently cancels the underlying Flight, the
        two operations serialise on the Flight.status field; if the
        cancellation lands first, the confirm is rejected with
        ERR_FLIGHT_NOT_BOOKABLE."

        PRD only pins the cancel-wins branch; we force that branch by
        committing the cancellation first and then attempting confirm,
        which the PRD sentence unambiguously requires to fail with
        ERR_FLIGHT_NOT_BOOKABLE.
        """
        member, flight, booking = setup_held_award_booking(
            member_balance=50_000,
        )
        member_hdr = make_member_headers(member["id"])
        # Cancel the flight first (cancel wins).
        cancel_resp = api.cancel_flight(flight["id"], admin_headers)
        validate_success(cancel_resp)
        # Now confirm must fail because the flight is no longer SCHEDULED.
        confirm_resp = api.confirm_award_booking(
            member["id"], booking["id"], member_hdr,
        )
        validate_error(confirm_resp, ApiErrorId.ERR_FLIGHT_NOT_BOOKABLE.value)


class TestIdempotencyRace:

    def test_concurrent_same_key_different_payload_yields_conflict(
        self, api,
    ):
        """PRD §2.11: "When two gift requests for the same sender
        arrive concurrently with identical idempotency_key values, the
        uniqueness of the (member_id, idempotency_key) pair on
        PointsTransaction admits exactly one writer. The second is
        rejected with ERR_IDEMPOTENCY_CONFLICT."

        We probe the differing-payload case (the one PRD names as the
        conflict path).
        """
        sender = create_member_with_balance(50_000)
        recipient_a = create_member()
        recipient_b = create_member()
        hdr = make_member_headers(sender["id"])

        results = run_race(
            lambda: api.send_gift(
                sender["id"],
                create_gift_payload(
                    recipient_a["id"], amount=1_000,
                    idempotency_key="race-key-1",
                ),
                hdr,
            ),
            lambda: api.send_gift(
                sender["id"],
                create_gift_payload(
                    recipient_b["id"], amount=1_500,
                    idempotency_key="race-key-1",
                ),
                hdr,
            ),
        )
        # Exactly one writer succeeds per PRD §2.11.
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        failure = outcome["failures"][0]
        # The loser MUST be ERR_IDEMPOTENCY_CONFLICT per PRD §2.11.
        validate_error(failure, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT.value)


class TestStatusMatchCoolingOffRace:

    def test_concurrent_approvals_inside_cooling_off_window(
        self, api, admin_headers,
    ):
        """PRD §2.11: "When two status-match approvals race inside the
        36-month cooling-off window of a prior grant, the two attempts
        serialise on the flip of Member.tier_source to STATUS_MATCH;
        the loser receives ERR_STATUS_MATCH_COOLING_OFF."
        """
        member = create_member()
        # Submit two PENDING status-match requests.
        smr1 = validate_success(
            api.create_status_match_request(
                member["id"],
                {"competitor_program": "X", "competitor_tier": "GOLD",
                 "evidence_url": "https://example.com/1"},
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        smr2 = validate_success(
            api.create_status_match_request(
                member["id"],
                {"competitor_program": "Y", "competitor_tier": "GOLD",
                 "evidence_url": "https://example.com/2"},
                make_member_headers(member["id"]),
            ),
            expected_status=201,
        )
        results = run_race(
            lambda: api.approve_status_match_request(
                member["id"], smr1["id"], admin_headers,
            ),
            lambda: api.approve_status_match_request(
                member["id"], smr2["id"], admin_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser MUST be ERR_STATUS_MATCH_COOLING_OFF per PRD §2.11.
        failure = outcome["failures"][0]
        validate_error(failure, ApiErrorId.ERR_STATUS_MATCH_COOLING_OFF.value)
