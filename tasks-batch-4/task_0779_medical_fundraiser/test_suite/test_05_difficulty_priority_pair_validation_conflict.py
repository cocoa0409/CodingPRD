"""Difficulty: priority_pair_validation_conflict — when two checks both fail on one
request, the higher-priority error (per the §2.10 fixed order) is the one returned.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    setup_published_campaign,
    setup_actor_trio,
    create_draft_campaign,
    place_hold,
    campaign_version,
    create_donation_payload,
    create_payout_payload,
    make_donor_headers,
    make_organizer_headers,
)


class TestStateBeatsFiscalOnDonation:
    """A 50-cent gift (below MIN 100) to a DRAFT campaign violates both state
    (priority 6, ERR_CAMPAIGN_NOT_ACTIVE) and fiscal (priority 10, ERR_AMOUNT_BELOW_MIN);
    the state error wins."""

    def test_below_min_gift_to_draft_returns_campaign_not_active(self, api):
        """PRD §2.10: "6. Target-resource state validity for the requested transition,
        including a campaign being ACTIVE before a donation is accepted (ERR_INVALID_STATE,
        409; the donation-specific variant is ERR_CAMPAIGN_NOT_ACTIVE, 409)."
        PRD §2.10: "10. Donation minimum amount (ERR_AMOUNT_BELOW_MIN, 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_donation
        """
        org, ben, donor = setup_actor_trio(api)
        camp = create_draft_campaign(api, org["id"], ben["id"])  # never published -> DRAFT
        resp = api.create_donation(
            create_donation_payload(camp["id"], donor["id"], 50), make_donor_headers(donor["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE, 409)

    def test_below_min_gift_to_active_returns_amount_below_min(self, api):
        """PRD §3.4: "Donations are accepted only while the campaign's lifecycle_status is
        ACTIVE; a gift to any other state is refused with ERR_CAMPAIGN_NOT_ACTIVE. The gift
        itself must be at least one dollar — 100 cents — otherwise it is rejected with
        ERR_AMOUNT_BELOW_MIN."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_donation
        """
        b = setup_published_campaign(api)  # ACTIVE, so state passes
        resp = api.create_donation(
            create_donation_payload(b["campaign"]["id"], b["donor"]["id"], 50),
            make_donor_headers(b["donor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_BELOW_MIN, 422)


class TestSafetyBeatsReferentialOnPayout:
    """A payout on a campaign that is both on HOLD and whose beneficiary is UNVERIFIED
    violates safety (priority 7, ERR_PAYOUT_ON_HOLD) and referential (priority 8,
    ERR_BENEFICIARY_NOT_VERIFIED); the safety error wins."""

    def test_hold_and_unverified_returns_payout_on_hold(self, api):
        """PRD §2.10: "7. Payout-posture safety — posture OPEN for payout operations
        (ERR_PAYOUT_ON_HOLD, 409) and not FROZEN for writes to a frozen campaign or its
        children (ERR_CAMPAIGN_FROZEN, 409)."
        PRD §2.10: "8. Beneficiary verification readiness for payouts
        (ERR_BENEFICIARY_NOT_VERIFIED, 409)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_payout
        """
        b = setup_published_campaign(api)  # beneficiary UNVERIFIED
        camp_id = b["campaign"]["id"]
        place_hold(api, camp_id)  # posture -> HOLD
        version = campaign_version(api, camp_id)
        resp = api.create_payout(
            create_payout_payload(camp_id, 1000, version),
            make_organizer_headers(b["organizer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYOUT_ON_HOLD, 409)

    def test_open_and_unverified_returns_beneficiary_not_verified(self, api):
        """PRD §3.7: "The beneficiary must be VERIFIED and withdrawal_ready, otherwise
        ERR_BENEFICIARY_NOT_VERIFIED."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_payout
        """
        b = setup_published_campaign(api)  # posture OPEN (no hold), beneficiary UNVERIFIED
        camp_id = b["campaign"]["id"]
        version = campaign_version(api, camp_id)
        resp = api.create_payout(
            create_payout_payload(camp_id, 1000, version),
            make_organizer_headers(b["organizer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BENEFICIARY_NOT_VERIFIED, 409)
