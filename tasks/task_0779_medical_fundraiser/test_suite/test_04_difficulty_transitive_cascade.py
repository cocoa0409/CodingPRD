"""Difficulty: transitive_cascade — multi-level cascades from a single trigger:
a dispute uphold that refunds a donation and holds an over-committed payout, and a
beneficiary rejection that freezes a campaign and cancels its in-flight payout.
"""
from test_helpers import (
    validate_success,
    setup_uphold_cascade_scenario,
    setup_reject_cascade_scenario,
    get_campaign,
    TEST_USERS,
)

TS_AGENT = TEST_USERS["ts_agent_headers"]


class TestUpholdRefundFreezesPayout:
    """Two net-10000 donations (provisional 19000), a REQUESTED payout of 19000,
    a dispute on D1 at UNDER_REVIEW. Uphold -> Refund -> D1 REFUNDED -> raised 10000 ->
    provisional < 0 -> payout ON_HOLD."""

    def test_uphold_refunds_donation_and_lowers_raised(self, api, guest_headers):
        """PRD §3.6: "Upholding it — valid from either UNDER_REVIEW or NEEDS_INFO, and only
        while the parent donation is still CAPTURED — records the resolution_note and then
        fires a four-level cascade: first it creates a Refund with reason DISPUTE_UPHELD and
        amount equal to the donation's net_to_campaign_cents; that refund drives the donation
        from CAPTURED to REFUNDED; the refund then recomputes the campaign's raised_cents,
        reserve_total_cents, provisional_available_cents, and settled_available_cents; and
        finally, if the provisional availability has gone negative, in-flight payouts are
        pulled onto hold as described in §3.7 until it is non-negative again."

        Design: Difficulty/transitive_cascade/dispute_uphold_refund_freezes_payout
        """
        s = setup_uphold_cascade_scenario(api)
        validate_success(api.uphold_dispute(s["dispute"]["id"], TS_AGENT))
        don = validate_success(api.get_donation(s["d1"]["id"], guest_headers))
        assert don["status"] == "REFUNDED", f"D1 -> REFUNDED, got {don['status']}"
        camp = get_campaign(api, s["camp_id"])
        assert camp["raised_cents"] == 10000, (
            f"raised drops from 20000 to 10000 after D1 refund, got {camp['raised_cents']}"
        )

    def test_uphold_holds_over_committed_payout(self, api, guest_headers):
        """PRD §3.7: "When a refund or hold recompute leaves a campaign's
        provisional_available_cents below zero — the campaign is over-committed — the system
        automatically pulls payouts in status REQUESTED or PROCESSING onto ON_HOLD, and an
        ON_HOLD payout is excluded from committed_cents."

        Design: Difficulty/transitive_cascade/dispute_uphold_refund_freezes_payout
        """
        s = setup_uphold_cascade_scenario(api)
        validate_success(api.uphold_dispute(s["dispute"]["id"], TS_AGENT))
        payout = validate_success(api.get_payout(s["payout"]["id"], guest_headers))
        assert payout["status"] == "ON_HOLD", (
            f"the over-committed payout is pulled to ON_HOLD, got {payout['status']}"
        )


class TestBeneficiaryRejectFreezesCampaignCancelsPayout:
    """Verified campaign with a net-10000 donation and a REQUESTED payout of 5000.
    Reject the beneficiary -> campaign FROZEN -> its REQUESTED payout CANCELLED."""

    def test_reject_freezes_campaign(self, api):
        """PRD §2.8: "When a beneficiary is rejected, every campaign of that beneficiary is
        driven to FROZEN, and — as a second-level cascade — each such campaign's payouts in
        status REQUESTED, PROCESSING, or ON_HOLD are moved to CANCELLED."

        Design: Difficulty/transitive_cascade/beneficiary_reject_freezes_campaign_cancels_payout
        """
        s = setup_reject_cascade_scenario(api)
        ben_data = validate_success(
            api.reject_verification(s["beneficiary"]["id"], {"reason": "FRAUD"}, TS_AGENT)
        )
        assert ben_data["verification_status"] == "REJECTED"
        camp = get_campaign(api, s["camp_id"])
        assert camp["payout_posture"] == "FROZEN", (
            f"the campaign is driven to FROZEN, got {camp['payout_posture']}"
        )

    def test_reject_cancels_in_flight_payout(self, api, guest_headers):
        """PRD §2.8: "When a beneficiary is rejected, every campaign of that beneficiary is
        driven to FROZEN, and — as a second-level cascade — each such campaign's payouts in
        status REQUESTED, PROCESSING, or ON_HOLD are moved to CANCELLED."

        Design: Difficulty/transitive_cascade/beneficiary_reject_freezes_campaign_cancels_payout
        """
        s = setup_reject_cascade_scenario(api)
        validate_success(
            api.reject_verification(s["beneficiary"]["id"], {"reason": "FRAUD"}, TS_AGENT)
        )
        payout = validate_success(api.get_payout(s["payout"]["id"], guest_headers))
        assert payout["status"] == "CANCELLED", (
            f"the REQUESTED payout is cancelled by the freeze cascade, got {payout['status']}"
        )
