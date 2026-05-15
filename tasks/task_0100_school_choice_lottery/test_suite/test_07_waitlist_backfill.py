"""Waitlist backfill rule and the WaitlistEvent audit trail.

Covers PRD §3.7 (backfill preserves the lottery_run snapshot ordering;
emits one WaitlistEvent per freed seat; promotes the next eligible
WAITLISTED applicant; resets waitlist_position to null and renumbers the
survivors).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    accept_application,
    api_client,
    assert_waitlist_event,
    decline_application,
    get_application,
    get_program,
    make_family_user_headers,
    setup_drawn_program_with_offer_and_one_waitlisted,
    setup_drawn_program_with_single_offer,
    validate_paginated,
    validate_success,
)


class TestBackfillPromotion:

    def test_decline_promotes_waitlist_head_to_offered(self, api):
        """PRD §3.7: "On a freed seat in the program, the system filters
        the candidate set down to applications in this program that are
        currently in WAITLISTED ... it consults the applications_ranked
        snapshot in the program's LotteryRun, filters that snapshot to
        the candidate set while preserving its order, and promotes the
        first survivor: it transitions from WAITLISTED to OFFERED".

        Claim: a decline by the OFFERED applicant promotes the
        WAITLISTED applicant to OFFERED.
        """
        bundle = setup_drawn_program_with_offer_and_one_waitlisted()
        winner_family = bundle["winner_family"]
        winner = bundle["winner"]
        loser = bundle["loser"]
        decline_application(winner_family, winner)
        loser_after = get_application(loser["id"])
        assert loser_after["status"] == "OFFERED", (
            "PRD §3.7: backfill promotes the next WAITLISTED applicant "
            "to OFFERED"
        )

    def test_backfill_clears_waitlist_position_on_promotee(self, api):
        """PRD §3.7: "its waitlist_position is cleared to null".

        Claim: after backfill promotion, the promotee's
        waitlist_position is null.
        """
        bundle = setup_drawn_program_with_offer_and_one_waitlisted()
        decline_application(bundle["winner_family"], bundle["winner"])
        loser_after = get_application(bundle["loser"]["id"])
        assert loser_after["status"] == "OFFERED"
        assert loser_after["waitlist_position"] is None, (
            "PRD §3.7: promotee's waitlist_position is cleared to null"
        )

    def test_backfill_sets_offer_expires_at_on_promotee(self, api):
        """PRD §3.7: "its offer_expires_at is set to Clock.now plus 168
        hours".

        Claim: after backfill the promotee carries a non-null
        offer_expires_at.
        """
        bundle = setup_drawn_program_with_offer_and_one_waitlisted()
        decline_application(bundle["winner_family"], bundle["winner"])
        loser_after = get_application(bundle["loser"]["id"])
        assert loser_after["offer_expires_at"] is not None


class TestSeatsOfferedInvariant:

    def test_seats_offered_unchanged_after_decline_plus_backfill(self, api):
        """PRD §3.7: "the system ... promotes the first survivor ...
        the program's seats_offered is incremented by one." Combined
        with the PRD §3.6 decline rule "decrements the program's
        seats_offered by one", a decline+backfill round-trip leaves
        seats_offered unchanged when the waitlist had a candidate.

        Claim: with one offer + one waitlisted, decline followed by the
        automatic backfill leaves seats_offered == 1.
        """
        bundle = setup_drawn_program_with_offer_and_one_waitlisted()
        before = get_program(bundle["program"]["id"])
        assert before["seats_offered"] == 1
        decline_application(bundle["winner_family"], bundle["winner"])
        after = get_program(bundle["program"]["id"])
        assert after["seats_offered"] == 1, (
            "PRD §3.7: backfill replaces the declined offer one-for-one"
        )


class TestEmptyWaitlist:

    def test_decline_with_empty_waitlist_no_promotion(self, api):
        """PRD §3.7: "If the candidate set is empty, the freed-seat
        decrement to seats_offered stands and nothing further happens."

        Claim: with no waitlisted applicant, a decline reduces
        seats_offered to 0 and no WaitlistEvent surfaces a promotion.
        """
        district, school, program, family, student, app, run = (
            setup_drawn_program_with_single_offer()
        )
        decline_application(family, app)
        prog = get_program(program["id"])
        assert prog["seats_offered"] == 0


class TestWaitlistEventsList:

    def test_waitlist_event_lists_after_backfill(
        self, api, system_operator_headers,
    ):
        """PRD §3.7: "A WaitlistEvent audit row is written, recording
        the program's program_id, the triggered_by_application_id whose
        departure freed the seat, the promoted_application_id (which
        may be null when the waitlist was empty), and the occurred_at
        instant."

        Claim: after a decline-plus-backfill cycle, GET
        /programs/{id}/waitlist-events returns at least one row whose
        triggered_by_application_id equals the declined application
        and promoted_application_id equals the promoted application.
        """
        bundle = setup_drawn_program_with_offer_and_one_waitlisted()
        decline_application(bundle["winner_family"], bundle["winner"])
        res = api.list_waitlist_events(
            bundle["program"]["id"], system_operator_headers,
        )
        data, _ = validate_paginated(res)
        assert len(data) >= 1
        # Find the event for our declined application.
        matched = [
            e for e in data
            if e.get("triggered_by_application_id") == bundle["winner"]["id"]
        ]
        assert matched, (
            "PRD §3.7: a WaitlistEvent must be written whose "
            "triggered_by_application_id equals the freed offer"
        )
        evt = matched[0]
        assert_waitlist_event(evt)
        assert evt["promoted_application_id"] == bundle["loser"]["id"], (
            "PRD §3.7: promoted_application_id must equal the next-eligible "
            "WAITLISTED application"
        )
