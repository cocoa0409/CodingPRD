"""Corner — state_machines section.

Invalid-transition and idempotency claims.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_chapter,
    create_round,
    create_and_open_party,
    complete_party,
    setup_round_with_proposed_bid_via_mutual_selection,
    make_chapter_officer_headers,
    make_pnm_headers,
    ApiErrorId,
    TEST_USERS,
)


class TestPartyOpenFromCompletedReturnsInvalidState:
    """A Party in COMPLETED has no /open transition out — priority 5 fires."""

    def test_open_completed_party_returns_invalid_state(self, api):
        """PRD §3.2: "A scheduled party becomes available for RSVPs when its `ChapterOfficer` transitions `status` from `SCHEDULED` to `OPEN`."
        PRD §2.7: "then state-machine precondition (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/corner_party_open_from_completed_returns_invalid_state
        """
        set_clock("2026-09-01T00:00:00Z")
        ch = create_chapter(
            name="OpenFromCompleted",
            greek_type="SORORITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 ofc")
        party = create_and_open_party(
            rnd["id"],
            ch["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
            capacity=5,
        )
        complete_party(party["id"], ch["id"])
        # Trigger: re-open from COMPLETED.
        res = api.open_party(party["id"], make_chapter_officer_headers(ch["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        # Party still COMPLETED.
        party_after = validate_success(
            api.get_party(party["id"], TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert party_after["status"] == "COMPLETED"


class TestBidMatchDeclineIdempotentRejectionFromDeclined:
    """A second decline against an already-DECLINED bid is rejected, not
    silently accepted."""

    def test_second_decline_returns_invalid_state(self, api):
        """PRD §3.6: "Declining a bid instead sets `BidMatch.status` to `DECLINED`, sets `PNM.status` to `BID_DECLINED`, clears `PNM.matched_chapter_id` to null, and bumps both versions — no dues entry is posted on decline."
        PRD §2.7: "then state-machine precondition (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/corner_bid_match_decline_idempotent_rejection_from_declined
        """
        ctx = setup_round_with_proposed_bid_via_mutual_selection(
            chapter_name="IdemChap",
            greek_type="FRATERNITY",
            quota_total=3,
            dues_per_member_cents=10000,
            legacy_priority_slots=0,
            pnm_full_name="IdemP",
            cycle_label="Fall 2026 idem",
        )
        bid_id = ctx["bid_match"]["id"]
        pnm_id = ctx["pnm"]["id"]
        # First decline succeeds.
        first = validate_success(
            api.decline_bid_match(bid_id, make_pnm_headers(pnm_id)), 200
        )
        assert first["status"] == "DECLINED"
        # Trigger: second decline.
        res = api.decline_bid_match(bid_id, make_pnm_headers(pnm_id))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        # Status unchanged.
        bid_after = validate_success(
            api.get_bid_match(bid_id, TEST_USERS["panhellenic_admin_headers"]),
            200,
        )
        assert bid_after["status"] == "DECLINED"
