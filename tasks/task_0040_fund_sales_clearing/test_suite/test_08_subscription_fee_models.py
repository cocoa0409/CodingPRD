"""PRD §3.5: Subscription fee calculation -- front-end vs back-end models.

The two variants share inputs but diverge on whether the tiered fee is
deducted before share minting (front-end) or deferred to redemption
(back-end). The same gross_amount_cents at the same NAV produces a
strict ordering: back-end-confirmed_shares > front-end-confirmed_shares
by exactly the amount that the front-end fee removed from the net.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    fee_tier,
    holding_period_tier,
    setup_basic_investor_and_fund,
    setup_investor_with_confirmed_subscribe,
    submit_subscribe_order,
    subscribe_confirm,
    validate_success,
)


class TestFrontEndSubscriptionFee:
    def test_front_end_fee_deducted_before_share_minting(self, api):
        """PRD §3.5: "When the toggle is false (front-end model), the
        server first locates the applicable subscription tier ... The
        chosen tier's `rate_bps` produces `subscription_fee_cents` as
        `gross_amount_cents` multiplied by `rate_bps`, divided by
        10,000, rounded half-up at cents. The net amount available for
        share minting is `gross_amount_cents` minus
        `subscription_fee_cents`, and `confirmed_shares` is the net
        amount multiplied by 100,000,000 then divided by the
        confirmation NAV (`nav_per_share_micros`), rounded half-up at
        the 1e-4 share unit."

        Claim: with rate=150 bps, gross=100_000 cents, NAV=1_000_000
        micros (initial-NAV path) -> fee=1_500, net=98_500,
        confirmed_shares=9_850_000.

        # difficulty: dual_variant_calc/subscription_fee_front_vs_back_end
        """
        investor, fund = setup_basic_investor_and_fund(
            cash_cents=10_000_000,
            fund_overrides={
                "subscription_fee_tiers": [fee_tier(0, None, 150)],
                "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
                "back_end_load_enabled": False,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        advance_clock_to("2026-11-01T10:00:00.000Z")
        order, nav = subscribe_confirm(
            investor, fund, gross_amount_cents=100_000,
        )
        assert order["status"] == "CONFIRMED"
        assert order["subscription_fee_cents"] == 1_500, (
            f"PRD §3.5 front-end fee: 100_000 * 150 / 10000 = 1500; "
            f"got {order['subscription_fee_cents']}"
        )
        assert order["confirmed_shares"] == 9_850_000, (
            f"PRD §3.5: net=98_500, NAV=1_000_000 micros; shares = "
            f"98_500 * 1e8 / 1_000_000 = 9_850_000; got "
            f"{order['confirmed_shares']}"
        )
        # PRD §3.5: "confirmed_amount_cents equals the original
        # gross_amount_cents -- that is the cash the investor's account
        # is actually debited."
        assert order["confirmed_amount_cents"] == 100_000

    def test_zero_bps_subscription_fee_full_share_minting(self, api):
        """PRD §3.5: front-end model with rate_bps=0 means
        subscription_fee_cents == 0 and confirmed_shares is the full
        gross_amount mint at the confirmation NAV.

        Claim: 100_000 cents at NAV=1.0 with 0-bps tiers -> fee=0,
        shares=10_000_000.
        """
        investor, fund, order, nav = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
        )
        assert order["subscription_fee_cents"] == 0
        assert order["confirmed_shares"] == 10_000_000


class TestBackEndSubscriptionFee:
    def test_back_end_fee_zero_at_confirmation_full_gross_to_shares(self, api):
        """PRD §3.5: "When `back_end_load_enabled` is true (back-end
        model), `subscription_fee_cents` is 0 at confirmation and
        `confirmed_shares` is `gross_amount_cents` multiplied by
        100,000,000 divided by the confirmation NAV, rounded half-up at
        the 1e-4 share unit; the back-end fee is deferred and collected
        at the eventual redemption."

        Claim: with rate=150 bps but back_end_load_enabled=true,
        gross=100_000, NAV=1.0 -> fee=0, confirmed_shares=10_000_000.

        # difficulty: dual_variant_calc/subscription_fee_front_vs_back_end
        """
        investor, fund = setup_basic_investor_and_fund(
            cash_cents=10_000_000,
            fund_overrides={
                "subscription_fee_tiers": [fee_tier(0, None, 150)],
                "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
                "back_end_load_enabled": True,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        advance_clock_to("2026-11-04T10:00:00.000Z")
        order, nav = subscribe_confirm(
            investor, fund, gross_amount_cents=100_000,
        )
        assert order["status"] == "CONFIRMED"
        assert order["subscription_fee_cents"] == 0, (
            f"PRD §3.5 back-end model: subscription_fee_cents=0 at "
            f"confirmation; got {order['subscription_fee_cents']}"
        )
        assert order["confirmed_shares"] == 10_000_000, (
            f"PRD §3.5 back-end model: confirmed_shares = gross * 1e8 / "
            f"nav_micros = 100_000 * 1e8 / 1_000_000 = 10_000_000; got "
            f"{order['confirmed_shares']}"
        )


class TestFrontVsBackInvariant:
    def test_back_end_yields_more_shares_than_front_end(self, api):
        """PRD §3.5: "The same gross amount produces strictly more
        shares under the back-end variant than under the front-end
        variant because no fee is removed from the net before share
        minting."

        Claim: with identical gross_amount, NAV, and tier rate, the
        back-end model's confirmed_shares is GREATER than the front-end
        model's confirmed_shares; specifically, the difference equals
        the fee divided by the per-share denominator (here 150_000
        share-units in 1e-4 unit).

        # difficulty: dual_variant_calc/subscription_fee_front_vs_back_end
        """
        # Front-end fund
        inv_a, fund_front = setup_basic_investor_and_fund(
            cash_cents=10_000_000,
            fund_overrides={
                "subscription_fee_tiers": [fee_tier(0, None, 150)],
                "back_end_load_enabled": False,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        # Back-end fund (separate investor to keep ledgers independent)
        inv_b, fund_back = setup_basic_investor_and_fund(
            cash_cents=10_000_000,
            fund_overrides={
                "subscription_fee_tiers": [fee_tier(0, None, 150)],
                "back_end_load_enabled": True,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        advance_clock_to("2026-11-08T10:00:00.000Z")
        order_front, _ = subscribe_confirm(
            inv_a, fund_front, gross_amount_cents=100_000
        )
        order_back, _ = subscribe_confirm(
            inv_b, fund_back, gross_amount_cents=100_000
        )
        assert order_front["status"] == "CONFIRMED"
        assert order_back["status"] == "CONFIRMED"
        assert order_back["confirmed_shares"] > order_front["confirmed_shares"], (
            f"PRD §3.5: same gross + same NAV produces strictly more "
            f"shares under back-end (got back={order_back['confirmed_shares']} "
            f"vs front={order_front['confirmed_shares']})"
        )
        # Concretely: back=10_000_000, front=9_850_000, delta=150_000.
        assert (
            order_back["confirmed_shares"]
            - order_front["confirmed_shares"]
        ) == 150_000
