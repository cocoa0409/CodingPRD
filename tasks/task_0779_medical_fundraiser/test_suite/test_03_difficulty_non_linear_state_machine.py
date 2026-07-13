"""Difficulty: non_linear_state_machine — the cyclic dispute review loop and the
two independent Campaign axes (lifecycle vs payout_posture).
"""
from test_helpers import (
    validate_success,
    setup_published_campaign,
    make_donation,
    open_dispute_under_review,
    place_hold,
    make_organizer_headers,
    make_donor_headers,
    TEST_USERS,
)

TS_AGENT = TEST_USERS["ts_agent_headers"]


class TestDisputeReviewCycle:
    """UNDER_REVIEW <-> NEEDS_INFO loop: request-info -> NEEDS_INFO, provide-info ->
    UNDER_REVIEW, and a second request-info returns to NEEDS_INFO (the cycle repeats)."""

    def test_provide_info_returns_to_under_review(self, api):
        """PRD §3.6: "the donor then provides information to move it from NEEDS_INFO back
        to UNDER_REVIEW, and this loop may repeat."

        Design: Difficulty/non_linear_state_machine/dispute_review_cycle
        """
        b = setup_published_campaign(api)
        don = make_donation(api, b["campaign"]["id"], b["donor"]["id"], 10000)
        donor_headers = make_donor_headers(b["donor"]["id"])
        dsp = open_dispute_under_review(api, don["id"], b["donor"]["id"], "NOT_AS_DESCRIBED")
        validate_success(api.request_info_dispute(dsp["id"], TS_AGENT))
        data = validate_success(api.provide_info_dispute(dsp["id"], donor_headers))
        assert data["status"] == "UNDER_REVIEW", (
            f"provide-info moves NEEDS_INFO back to UNDER_REVIEW, got {data['status']}"
        )

    def test_second_request_info_repeats_cycle_to_needs_info(self, api):
        """PRD §3.6: "requesting more information moves it from UNDER_REVIEW to NEEDS_INFO;
        the donor then provides information to move it from NEEDS_INFO back to UNDER_REVIEW,
        and this loop may repeat."

        Design: Difficulty/non_linear_state_machine/dispute_review_cycle
        """
        b = setup_published_campaign(api)
        don = make_donation(api, b["campaign"]["id"], b["donor"]["id"], 10000)
        donor_headers = make_donor_headers(b["donor"]["id"])
        dsp = open_dispute_under_review(api, don["id"], b["donor"]["id"], "NOT_AS_DESCRIBED")
        validate_success(api.request_info_dispute(dsp["id"], TS_AGENT))        # NEEDS_INFO
        validate_success(api.provide_info_dispute(dsp["id"], donor_headers))   # UNDER_REVIEW
        data = validate_success(api.request_info_dispute(dsp["id"], TS_AGENT))  # NEEDS_INFO again
        assert data["status"] == "NEEDS_INFO", (
            f"the loop repeats: second request-info -> NEEDS_INFO, got {data['status']}"
        )


class TestCampaignParallelAxes:
    """An ACTIVE Hold drives payout_posture OPEN->HOLD without touching
    lifecycle_status; a later pause moves lifecycle ACTIVE->PAUSED while posture stays HOLD."""

    def test_pause_moves_lifecycle_to_paused(self, api):
        """PRD §3.2: "Pausing takes an ACTIVE campaign to PAUSED; resuming takes a PAUSED
        campaign back to ACTIVE; each requires its exact starting state, otherwise
        ERR_INVALID_STATE."

        Design: Difficulty/non_linear_state_machine/campaign_parallel_lifecycle_and_posture
        """
        b = setup_published_campaign(api)
        camp_id = b["campaign"]["id"]
        place_hold(api, camp_id)
        data = validate_success(
            api.pause_campaign(camp_id, make_organizer_headers(b["organizer"]["id"]))
        )
        assert data["lifecycle_status"] == "PAUSED", (
            f"pause moves lifecycle to PAUSED, got {data['lifecycle_status']}"
        )

    def test_posture_stays_hold_across_pause(self, api):
        """PRD §2.8: "Independently of its lifecycle, every campaign carries a computed
        payout_posture with three values — OPEN, HOLD, and FROZEN — recomputed whenever a
        hold is placed or released or the beneficiary's verification changes."

        Design: Difficulty/non_linear_state_machine/campaign_parallel_lifecycle_and_posture
        """
        b = setup_published_campaign(api)
        camp_id = b["campaign"]["id"]
        place_hold(api, camp_id)
        data = validate_success(
            api.pause_campaign(camp_id, make_organizer_headers(b["organizer"]["id"]))
        )
        assert data["payout_posture"] == "HOLD", (
            f"posture stays HOLD (an ACTIVE hold) across a lifecycle pause, "
            f"got {data['payout_posture']}"
        )
