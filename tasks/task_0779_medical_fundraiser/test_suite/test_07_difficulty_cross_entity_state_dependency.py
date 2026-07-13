"""Difficulty: cross_entity_state_dependency — an operation on one entity gated by
the state of a different entity: payout gated by Beneficiary.verification_status, and
dispute-open gated by Donation.status.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_published_campaign,
    setup_actor_trio,
    submit_beneficiary_pending,
    create_active_campaign,
    make_donation,
    campaign_version,
    create_payout_payload,
    create_dispute_payload,
    make_organizer_headers,
    make_donor_headers,
)


class TestPayoutRequiresBeneficiaryVerified:
    """With the beneficiary not VERIFIED (posture OPEN, no holds) a payout request is
    rejected with ERR_BENEFICIARY_NOT_VERIFIED."""

    def test_unverified_beneficiary_blocks_payout(self, api):
        """PRD §3.7: "The beneficiary must be VERIFIED and withdrawal_ready, otherwise
        ERR_BENEFICIARY_NOT_VERIFIED."

        Design: Difficulty/cross_entity_state_dependency/payout_requires_beneficiary_verified
        """
        b = setup_published_campaign(api)  # beneficiary UNVERIFIED
        camp_id = b["campaign"]["id"]
        resp = api.create_payout(
            create_payout_payload(camp_id, 1000, campaign_version(api, camp_id)),
            make_organizer_headers(b["organizer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_NOT_VERIFIED, 409)

    def test_pending_beneficiary_blocks_payout(self, api):
        """PRD §3.7: "The beneficiary must be VERIFIED and withdrawal_ready, otherwise
        ERR_BENEFICIARY_NOT_VERIFIED."

        Design: Difficulty/cross_entity_state_dependency/payout_requires_beneficiary_verified
        """
        org, ben, donor = setup_actor_trio(api)
        submit_beneficiary_pending(api, ben["id"])  # PENDING, not VERIFIED
        camp = create_active_campaign(api, org["id"], ben["id"])
        resp = api.create_payout(
            create_payout_payload(camp["id"], 1000, campaign_version(api, camp["id"])),
            make_organizer_headers(org["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_NOT_VERIFIED, 409)


class TestDisputeRequiresDonationCaptured:
    """Opening a dispute is gated by the donation being CAPTURED: on a REFUNDED donation
    the open is rejected ERR_INVALID_STATE."""

    def test_dispute_on_refunded_donation_rejected(self, api):
        """PRD §3.6: "A dispute is opened on a CAPTURED donation by the donor or a Trust &
        Safety agent, supplying the donation_id and a reason (one of FRAUD, UNAUTHORIZED,
        NOT_AS_DESCRIBED, or OTHER)."
        PRD §3.6: "Refunding is valid only while the donation is CAPTURED, otherwise
        ERR_INVALID_STATE; it drives the donation from CAPTURED to the terminal REFUNDED,
        and recomputes the campaign's raised_cents, reserve_total_cents, and both
        availability figures."

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_donation_captured
        """
        b = setup_published_campaign(api)
        donor_id = b["donor"]["id"]
        don = make_donation(api, b["campaign"]["id"], donor_id, 10000)
        validate_success(api.refund_donation(don["id"], make_donor_headers(donor_id)), 201)
        resp = api.create_dispute(
            create_dispute_payload(don["id"], "FRAUD"), make_donor_headers(donor_id)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_dispute_on_captured_donation_succeeds(self, api):
        """PRD §3.6: "A dispute is opened on a CAPTURED donation by the donor or a Trust &
        Safety agent, supplying the donation_id and a reason (one of FRAUD, UNAUTHORIZED,
        NOT_AS_DESCRIBED, or OTHER). A new dispute is OPEN, and opening it recomputes the
        campaign's disputed_locked_cents, which pins the disputed donation's net out of
        settled availability."

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_donation_captured
        """
        b = setup_published_campaign(api)
        donor_id = b["donor"]["id"]
        don = make_donation(api, b["campaign"]["id"], donor_id, 10000)  # CAPTURED
        data = validate_success(
            api.create_dispute(create_dispute_payload(don["id"], "FRAUD"),
                               make_donor_headers(donor_id)),
            201,
        )
        assert data["status"] == "OPEN", f"a new dispute is OPEN, got {data['status']}"
