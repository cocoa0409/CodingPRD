"""Investment validation and funding-race transitions.

PRD §3.3, §3.4. Covers diversification cap, denomination, oversubscription,
cross-platform, insufficient cash, and the system-driven
OPEN -> FUNDED transition.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    INVESTMENT_MIN_CENTS,
    INVESTMENT_MULTIPLE_CENTS,
    assert_investment,
    create_investment,
    create_investment_payload,
    deposit_to_investor,
    find_disclosure,
    get_investor,
    get_listing,
    make_investor_headers,
    setup_funded_investor,
    setup_funded_listing,
    setup_open_listing,
    setup_platform_with_officer,
    validate_error,
    validate_success,
)


# ===========================================================================
# Denomination — PRD §3.3
# ===========================================================================
class TestInvestmentDenomination:

    def test_amount_below_minimum_rejected(self, api):
        """PRD §3.3: "The pledge's denomination must be at least 2,500
        cents and a positive integer multiple of 100 cents; otherwise
        the create is rejected with ERR_INVESTMENT_DENOMINATION and
        HTTP 422."

        Claim: amount_cents=2400 (below 2500) ->
        ERR_INVESTMENT_DENOMINATION.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(platform["id"])
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=2400),
            make_investor_headers(investor["id"]),
        )
        validate_error(resp, "ERR_INVESTMENT_DENOMINATION")

    def test_amount_not_multiple_of_hundred_rejected(self, api):
        """PRD §3.3: "a positive integer multiple of 100 cents".

        Claim: amount_cents=3001 (not a multiple of 100) ->
        ERR_INVESTMENT_DENOMINATION.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(platform["id"])
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=3001),
            make_investor_headers(investor["id"]),
        )
        validate_error(resp, "ERR_INVESTMENT_DENOMINATION")

    def test_minimum_amount_at_2500_accepted(self, api):
        """PRD §3.3: "at least 2,500 cents" — 2500 is INCLUSIVE.

        Claim: amount_cents=2500 on a listing with principal>=2500 is
        accepted.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=10_000,
        )
        investor = setup_funded_investor(platform["id"])
        inv = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=2500,
        )
        assert_investment(inv)
        assert inv["amount_cents"] == 2500
        assert inv["status"] == "COMMITTED"


# ===========================================================================
# Cross-platform — PRD §3.3
# ===========================================================================
class TestCrossPlatformInvestment:

    def test_investor_on_different_platform_rejected(self, api):
        """PRD §3.3: "The investor's platform_id must match the
        listing's platform_id; a cross-platform pledge yields
        ERR_CROSS_PLATFORM_INVESTMENT."

        Claim: an investor created on platform A pledging into a
        listing on platform B -> ERR_CROSS_PLATFORM_INVESTMENT.
        """
        platform_a, officer_a, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        # Create a second platform and an investor on it.
        platform_b, _ = setup_platform_with_officer()
        investor_b = setup_funded_investor(platform_b["id"])
        # The investor is on platform_b but tries to pledge on
        # listing under platform_a. The investor_id won't resolve under
        # platform_a — but the operative rule is platform mismatch.
        resp = api.create_investment(
            platform_a["id"], listing["id"],
            create_investment_payload(amount_cents=2500),
            make_investor_headers(investor_b["id"]),
        )
        # Acceptable: either the investor record is not found under
        # platform_a (ERR_NOT_FOUND from path-resolution check on
        # investor lookup), or the explicit cross-platform check fires.
        # PRD §3.3 names the cross-platform rule explicitly — assert
        # exactly that (PRD §2.9 places it before diversification/cash).
        validate_error(resp, "ERR_CROSS_PLATFORM_INVESTMENT")


# ===========================================================================
# Insufficient cash — PRD §3.3
# ===========================================================================
class TestInsufficientCash:

    def test_investor_below_cash_rejected(self, api):
        """PRD §3.3: "The investor's cash_balance_cents must be at
        least the proposed amount_cents; otherwise the create is
        rejected with ERR_INSUFFICIENT_CASH."

        Claim: investor with cash_balance_cents=1000 pledging 2500 ->
        ERR_INSUFFICIENT_CASH.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        # Investor with committed_capital high enough to keep the
        # diversification cap from preempting; but only 1000 cents
        # cash.
        investor = setup_funded_investor(
            platform["id"],
            committed_capital_cents=10_000_000,
            deposit_cents=1000,
        )
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=2500),
            make_investor_headers(investor["id"]),
        )
        validate_error(resp, "ERR_INSUFFICIENT_CASH")


# ===========================================================================
# Diversification cap — PRD §3.3
# ===========================================================================
class TestDiversificationCap:

    def test_exposure_exactly_at_cap_allowed(self, api):
        """PRD §3.3: "The comparison is inclusive: exposure exactly
        equal to the cap is allowed".

        Claim: an investor with committed_capital=10_000_00,
        concentration=1000 (so cap=100_000 cents), pledging exactly
        100_000 cents to one borrower is allowed.
        """
        # max_borrower_concentration_bps default 1000 is used.
        platform, officer, b, listing = setup_open_listing(
            principal_cents=500_000_00,
        )
        investor = setup_funded_investor(
            platform["id"],
            committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        inv = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=100_000,
        )
        assert inv["status"] == "COMMITTED"
        assert inv["amount_cents"] == 100_000

    def test_exposure_one_cent_over_cap_rejected(self, api):
        """PRD §3.3: "anything strictly greater is rejected with
        ERR_DIVERSIFICATION_CAP_EXCEEDED."

        Claim: with cap=100_000, two investments summing to 100_100
        cents on the same borrower -> second is rejected.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=500_000_00,
        )
        investor = setup_funded_investor(
            platform["id"],
            committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=100_000,
        )
        # Second pledge of 100 cents would push exposure to 100_100 >
        # cap=100_000.
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=100),
            make_investor_headers(investor["id"]),
        )
        validate_error(resp, "ERR_DIVERSIFICATION_CAP_EXCEEDED")


# ===========================================================================
# Oversubscription — PRD §3.3
# ===========================================================================
class TestOversubscription:

    def test_pledge_above_remaining_principal_rejected(self, api):
        """PRD §3.3: "the pledge cannot drive the listing's
        pledged_cents past principal_cents; any oversubscription yields
        ERR_LISTING_OVERSUBSCRIBED."

        Claim: pledging amount > principal_cents - pledged_cents ->
        ERR_LISTING_OVERSUBSCRIBED.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=10_000,
        )
        investor_a = setup_funded_investor(
            platform["id"], committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        create_investment(
            platform["id"], listing["id"], investor_a["id"],
            amount_cents=5_000,
        )
        # Listing now has pledged_cents=5_000, remaining 5_000.
        investor_b = setup_funded_investor(
            platform["id"], committed_capital_cents=10_000_00,
            deposit_cents=10_000_00,
        )
        resp = api.create_investment(
            platform["id"], listing["id"],
            create_investment_payload(amount_cents=5_100),
            make_investor_headers(investor_b["id"]),
        )
        validate_error(resp, "ERR_LISTING_OVERSUBSCRIBED")


# ===========================================================================
# Successful pledge side effects — PRD §3.3
# ===========================================================================
class TestSuccessfulPledge:

    def test_pledge_decrements_investor_cash(self, api):
        """PRD §3.3: "When the create succeeds, the server decrements
        the investor's cash_balance_cents by amount_cents".

        Claim: a successful pledge reduces investor.cash_balance_cents
        by exactly amount_cents.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(
            platform["id"], deposit_cents=10_000_00,
        )
        cash_before = investor["cash_balance_cents"]
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=10_000,
        )
        refreshed = get_investor(platform["id"], investor["id"])
        assert refreshed["cash_balance_cents"] == cash_before - 10_000

    def test_pledge_adds_to_listing_pledged_cents(self, api):
        """PRD §3.3: "increases the listing's pledged_cents by the
        same amount".
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(platform["id"])
        create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=10_000,
        )
        refreshed = get_listing(platform["id"], listing["id"])
        assert refreshed["pledged_cents"] == 10_000

    def test_pledge_filling_principal_transitions_listing_to_funded(
        self, api,
    ):
        """PRD §3.3: "If the new pledged_cents exactly equals
        principal_cents, the listing transitions OPEN -> FUNDED in the
        same operation, and a draft Disclosure with kind LISTING_FUNDED
        is emitted."

        Claim: a single investment whose amount equals principal_cents
        drives the listing to FUNDED.
        """
        (platform, officer, b, investor, listing,
         investment) = setup_funded_listing(principal_cents=100_000)
        assert listing["status"] == "FUNDED"
        assert listing["pledged_cents"] == 100_000

    def test_pledge_filling_principal_emits_listing_funded_disclosure(
        self, api,
    ):
        """PRD §3.3: "a draft Disclosure with kind LISTING_FUNDED is
        emitted."

        Claim: after the final pledge, a DRAFT LISTING_FUNDED
        disclosure exists for the listing.
        """
        (platform, officer, b, investor, listing,
         investment) = setup_funded_listing(principal_cents=100_000)
        d = find_disclosure(
            platform["id"], subject_type="LISTING",
            subject_id=listing["id"], kind="LISTING_FUNDED",
            published=False,
        )
        assert d is not None, "expected a DRAFT LISTING_FUNDED disclosure"
        assert d["published"] is False

    def test_initial_share_bps_is_zero_for_committed(self, api):
        """PRD §3.3: "persists the new Investment with status COMMITTED
        and share_bps initialized to 0 (it is only filled in at
        CONVERTED)."

        Claim: a freshly committed investment carries share_bps == 0.
        """
        platform, officer, b, listing = setup_open_listing(
            principal_cents=100_000,
        )
        investor = setup_funded_investor(platform["id"])
        inv = create_investment(
            platform["id"], listing["id"], investor["id"],
            amount_cents=10_000,
        )
        assert inv["status"] == "COMMITTED"
        assert inv["share_bps"] == 0
