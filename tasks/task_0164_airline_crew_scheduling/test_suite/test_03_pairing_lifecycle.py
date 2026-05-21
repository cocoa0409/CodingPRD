"""Pairing lifecycle transitions: DRAFT -> PUBLISHED -> BIDDING_OPEN.

Also covers cancellation from BIDDING_OPEN and AWARDED, and the
24-hour cutoff on opening bidding.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    PairingStatus,
    add_hours_iso,
    add_minutes_iso,
    build_pairing_with_one_duty_period,
    cancel_pairing,
    create_crew_member,
    create_pairing_draft,
    get_crew_member,
    get_pairing,
    iso_from_dt,
    iso_now_utc,
    open_bidding,
    open_bidding_payload,
    publish_and_open_bidding,
    publish_pairing,
    scheduler_headers,
    setup_pairing_admin_assigned,
    submit_bid,
    validate_error,
    validate_success,
)


class TestPublishLifecycle:

    def test_publish_transitions_draft_to_published(self, api):
        """PRD §3.1: "Publishing a draft pairing moves it to PUBLISHED."""
        pairing, _, _ = build_pairing_with_one_duty_period()
        published = publish_pairing(pairing["id"])
        assert published["status"] == PairingStatus.PUBLISHED.value


class TestOpenBidding:

    def test_open_bidding_requires_24h_lead(self, api, scheduler_headers):
        """PRD §3.2: "The transition is rejected unless Pairing.start_at
        is at least 24 hours in the future."
        """
        # Build pairing with start_at only 2 hours in the future.
        in_2h = iso_from_dt(datetime.now(timezone.utc) + timedelta(hours=2))
        pairing, _, _ = build_pairing_with_one_duty_period(start_at=in_2h)
        publish_pairing(pairing["id"])
        resp = api.open_bidding(
            pairing["id"],
            open_bidding_payload(bid_window_id="BW-TOO-SOON"),
            scheduler_headers,
        )
        # PRD §3.2 explicitly names ERR_PAIRING_INVALID_STATE for an
        # open-bidding attempt against a pairing that is not PUBLISHED.
        # PRD does not commit a specific error_id to "PUBLISHED but
        # start_at too soon". Accept the broader pairing-state family.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_PAIRING_INVALID_STATE.value,
            ApiErrorId.ERR_VALIDATION_FAILED.value,
        ])

    def test_open_bidding_on_draft_pairing_rejected(self, api,
                                                     scheduler_headers):
        """PRD §3.2: "The API responds with ERR_PAIRING_INVALID_STATE if
        the pairing is not PUBLISHED (for example, the scheduler tried
        to open bidding on a DRAFT or already-AWARDED pairing)."
        """
        pairing, _, _ = build_pairing_with_one_duty_period()
        resp = api.open_bidding(
            pairing["id"],
            open_bidding_payload(bid_window_id="BW-X"),
            scheduler_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PAIRING_INVALID_STATE.value)


class TestCancellationFromBiddingOpen:

    def test_cancel_from_bidding_open_marks_submitted_bids_not_awarded(
        self, api,
    ):
        """PRD §3.7: "Cancelling from BIDDING_OPEN transitions all
        SUBMITTED bids on the pairing to NOT_AWARDED, and if any bids
        were already AWARDED, they too become NOT_AWARDED and their
        Assignment rows are moved to RELEASED."

        Tests the SUBMITTED-side: build a BIDDING_OPEN pairing with a
        submitted bid, cancel, verify pairing transitions to CANCELLED.
        Bid-row status check is omitted because PRD §4 does not declare
        a GET /bids endpoint to read it back.
        """
        bidder = create_crew_member(rank="CAPTAIN")
        from test_helpers import setup_pairing_in_bidding
        pairing, bw = setup_pairing_in_bidding(
            required_rank_composition={"CAPTAIN": 1},
        )
        submit_bid(bidder, pairing["id"], bw, preference_rank=1)
        cancelled = cancel_pairing(pairing["id"])
        assert cancelled["status"] == PairingStatus.CANCELLED.value, (
            "PRD §3.7 cancel from BIDDING_OPEN."
        )


class TestCancellationFromAwarded:

    def test_cancel_from_awarded_releases_assignments_and_debits_counters(
        self, api,
    ):
        """PRD §3.7: "Cancelling from AWARDED releases every AWARDED
        assignment on the pairing: the assignment transitions to
        RELEASED, the crew member's cumulative_block_minutes_30d is
        debited by Assignment.scheduled_block_minutes if
        Pairing.start_at falls within the rolling 30-day window from
        now, and the crew member's cumulative_duty_minutes_7d is
        debited by Pairing.total_duty_minutes if Pairing.end_at falls
        within the rolling 7-day window from now."

        # difficulty: transitive_cascade/pairing_cancel_chain_depth_2
        # difficulty: compensating_invariant/pairing_cancel_undo_conserves_baseline_block_30d
        """
        pilot = create_crew_member(rank="CAPTAIN")
        # Set start_at within rolling 30d window (e.g., +5 days from now).
        in_5d = iso_from_dt(
            datetime.now(timezone.utc) + timedelta(days=5),
        )
        pairing, assignment = setup_pairing_admin_assigned(
            pilot, assigned_rank_slot="CAPTAIN",
            start_at=in_5d,
            revenue_block_minutes=400,
            duty_minutes=520,
        )
        # Snapshot baseline.
        before = get_crew_member(pilot["id"])
        block_before = int(before["cumulative_block_minutes_30d"])
        # Cancel.
        cancelled = cancel_pairing(pairing["id"])
        assert cancelled["status"] == PairingStatus.CANCELLED.value

        # Re-read crew member; cumulative_block_minutes_30d debited by
        # Assignment.scheduled_block_minutes.
        after = get_crew_member(pilot["id"])
        block_after = int(after["cumulative_block_minutes_30d"])
        sched_block = int(assignment["scheduled_block_minutes"])
        assert block_after == block_before - sched_block, (
            f"PRD §3.7 debit by scheduled_block_minutes; expected "
            f"{block_before - sched_block}, got {block_after}"
        )

        # Re-read assignment.
        from test_helpers import get_assignment
        a = get_assignment(assignment["id"])
        assert a["status"] == "RELEASED", (
            "PRD §3.7: AWARDED assignments are released on cancel."
        )
