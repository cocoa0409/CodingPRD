"""Cross-entity state dependencies that the PRD explicitly enforces.

Bid creation depends on Pairing.status == BIDDING_OPEN; trade approval
depends on both assignments still being SCHEDULED.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    accept_trade_as,
    create_bid_payload,
    create_crew_member,
    create_trade_request,
    crew_role_headers,
    open_bidding,
    publish_pairing,
    random_bid_window_id,
    release_assignment,
    scheduler_headers,
    setup_pairing_in_bidding,
    setup_two_pilots_with_assignments,
    submit_bid,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestBidRequiresBiddingOpen:

    def test_bid_on_published_not_open_pairing_rejected(self, api):
        """PRD §3.2: "Once a pairing is PUBLISHED, the scheduler may
        open bidding on it by associating it with a bid_window_id,
        transitioning the pairing from PUBLISHED to BIDDING_OPEN ... A
        bid against a pairing that is no longer BIDDING_OPEN is
        rejected with ERR_BID_WINDOW_CLOSED if the pairing has just
        left that state through an awarding sweep, or with
        ERR_PAIRING_INVALID_STATE otherwise."

        # difficulty: cross_entity_state_dependency/bid_submission_requires_pairing_bidding_open
        Test: PUBLISHED → bid → ERR_PAIRING_INVALID_STATE; then
        open-bidding → bid succeeds.
        """
        from test_helpers import (
            build_pairing_with_one_duty_period,
        )
        pilot = create_crew_member(rank="CAPTAIN")
        pairing, _, _ = build_pairing_with_one_duty_period(
            required_rank_composition={"CAPTAIN": 1},
        )
        publish_pairing(pairing["id"])
        bw = random_bid_window_id()
        # Bid while still PUBLISHED.
        resp = api.create_bid(
            create_bid_payload(pairing["id"], bw, preference_rank=1),
            crew_role_headers(pilot),
        )
        validate_error(resp, ApiErrorId.ERR_PAIRING_INVALID_STATE.value)
        # Open bidding and retry.
        open_bidding(pairing["id"], bid_window_id=bw)
        resp2 = api.create_bid(
            create_bid_payload(pairing["id"], bw, preference_rank=1),
            crew_role_headers(pilot),
        )
        validate_success(resp2, expected_status=201)


class TestTradeApproveBothAssignmentsScheduled:

    def test_approve_rejected_when_counterparty_released(self, api):
        """PRD §3.8: "Approval is rejected with
        ERR_INVALID_ASSIGNMENT_STATE if either assignment is no longer
        SCHEDULED at approval time."

        # difficulty: cross_entity_state_dependency/trade_approve_requires_both_assignments_scheduled
        Second test for the instance — release the *counterparty* side
        (the first test in test_08 released initiator-side).
        """
        m1, m2, a1, a2 = setup_two_pilots_with_assignments()
        tr = create_trade_request(m1, m2, a1, a2)
        accept_trade_as(m2, tr["id"])
        # Release the counterparty's assignment between accept and
        # approve.
        release_assignment(a2["id"])
        resp = api.approve_trade_request(tr["id"], scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value)
