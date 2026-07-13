"""Difficulty: boundary_precision_check — numeric thresholds tested at and across
their boundaries: the 100-cent donation minimum and the zero settled-availability edge.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    setup_published_campaign,
    make_donation,
    get_campaign,
    campaign_version,
    create_donation_payload,
    create_payout_payload,
    make_donor_headers,
    make_organizer_headers,
)


class TestDonationMinimumBoundary:
    """amount 100 (== MIN) is accepted; amount 99 is rejected. Boundary is >= 100."""

    def test_donation_at_minimum_is_accepted(self, api):
        """PRD §3.4: "The gift itself must be at least one dollar — 100 cents — otherwise
        it is rejected with ERR_AMOUNT_BELOW_MIN."

        Design: Difficulty/boundary_precision_check/donation_min_amount_boundary
        """
        b = setup_published_campaign(api)
        don = make_donation(api, b["campaign"]["id"], b["donor"]["id"], 100)
        assert don["amount_cents"] == 100
        assert don["status"] == "CAPTURED"

    def test_donation_below_minimum_is_rejected(self, api):
        """PRD §3.4: "The gift itself must be at least one dollar — 100 cents — otherwise
        it is rejected with ERR_AMOUNT_BELOW_MIN."

        Design: Difficulty/boundary_precision_check/donation_min_amount_boundary
        """
        b = setup_published_campaign(api)
        resp = api.create_donation(
            create_donation_payload(b["campaign"]["id"], b["donor"]["id"], 99),
            make_donor_headers(b["donor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_BELOW_MIN, 422)


class TestPayoutZeroAvailableEmptyDonationSet:
    """A verified campaign with zero CAPTURED donations has settled_available_cents == 0,
    so a payout of 1 cent (the smallest positive draw) is rejected."""

    def test_settled_available_is_zero_with_no_donations(self, api):
        """PRD §2.6: "Settled (pessimistic) availability, settled_available_cents, equals
        provisional_available_cents minus disputed_locked_cents minus hold_locked_cents."

        Design: Difficulty/boundary_precision_check/payout_zero_available_empty_donation_set
        """
        b = setup_published_campaign(api, verified=True)
        camp = get_campaign(api, b["campaign"]["id"])
        assert camp["settled_available_cents"] == 0, (
            f"no donations -> settled_available 0, got {camp['settled_available_cents']}"
        )

    def test_one_cent_payout_over_zero_available_is_rejected(self, api):
        """PRD §3.7: "The requested amount must not exceed the campaign's
        settled_available_cents — equality is permitted — otherwise ERR_INSUFFICIENT_AVAILABLE
        (HTTP 402)."

        Design: Difficulty/boundary_precision_check/payout_zero_available_empty_donation_set
        """
        b = setup_published_campaign(api, verified=True)
        camp_id = b["campaign"]["id"]
        version = campaign_version(api, camp_id)
        resp = api.create_payout(
            create_payout_payload(camp_id, 1, version),
            make_organizer_headers(b["organizer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE, 402)
