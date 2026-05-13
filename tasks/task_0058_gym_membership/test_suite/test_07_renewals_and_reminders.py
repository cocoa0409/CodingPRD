"""Renewal quotes, reminder sweep, and lapse handling.

PRD §3.7.
"""
from __future__ import annotations
import pytest
from datetime import timedelta

from test_helpers import (
    PA, SO,
    advance_clock,
    get_card,
    iso_z, parse_iso,
    setup_annual_card_at_remaining_days,
    setup_monthly_card_for_refund_eligibility,
    validate_success,
)


# ===========================================================================
# Renewal-quote band boundaries (PRD §3.7)
# ===========================================================================
class TestRenewalQuote:

    def test_more_than_30_days_full_price(self, api):
        """PRD §3.7: 'When that value is greater than 30, no discount
        applies and the quote equals CardType.price_cents.'"""
        _, _, card = setup_annual_card_at_remaining_days(
            remaining_days=200,
            price_cents=100_000,
        )
        data = validate_success(
            api.get_renewal_quote(card["id"], SO),
            expected_status=200,
        )
        assert data.get("renewal_price_cents") == 100_000, (
            f"PRD §3.7: > 30 days → no discount, quote == price_cents; "
            f"got {data!r}"
        )

    def test_inside_30_day_window_discount_applies(self, api):
        """PRD §3.7: 'When it is at least 7 and no more than 30, the
        discount in basis points equals
        CardType.renewal_discount_pct_bp.'

        price 30000, discount 1500bp → 30000 * (10000 - 1500) / 10000
        = 25500.
        """
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=15,
            refund_eligibility_days=0,
            validity_days=30,
            price_cents=30_000,
        )
        # The setup_monthly_card_for_refund_eligibility helper uses
        # create_monthly_card_type which defaults
        # renewal_discount_pct_bp=1500.
        data = validate_success(
            api.get_renewal_quote(card["id"], SO),
            expected_status=200,
        )
        assert data.get("renewal_price_cents") == 25_500, (
            "PRD §3.7: in [7,30] days discount == "
            "renewal_discount_pct_bp; 30000 * (10000-1500)/10000 = 25500."
        )

    def test_inside_7_day_urgent_window_adds_500bp(self, api):
        """PRD §3.7: 'When it is at least 0 and no more than 6, the
        discount is CardType.renewal_discount_pct_bp plus 500 basis
        points — an extra five percentage points inside the final
        week.'

        renewal_discount_pct_bp = 0; days_to_expiry = 5; total
        discount = 0 + 500 = 500 bp. 30000 * 9500 / 10000 = 28500.
        """
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=5,
            refund_eligibility_days=0,
            validity_days=30,
            price_cents=30_000,
        )
        # Override renewal_discount_pct_bp via a custom CT? The helper
        # used default 1500 bp. Recompute expected: 1500 + 500 = 2000
        # bp → 30000 * 8000 / 10000 = 24000.
        data = validate_success(
            api.get_renewal_quote(card["id"], SO),
            expected_status=200,
        )
        assert data.get("renewal_price_cents") == 24_000, (
            "PRD §3.7: in [0,6] discount = base + 500 bp; here 1500+500="
            "2000 → 30000*8000/10000 = 24000."
        )

    def test_lapsed_card_no_discount(self, api):
        """PRD §3.7: 'When the card has already lapsed (days-to-expiry
        is negative), the discount is zero.'

        Set up a card already past its expiry by advancing clock.
        """
        _, _, card = setup_monthly_card_for_refund_eligibility(
            remaining_days=-5,
            refund_eligibility_days=0,
            validity_days=30,
            price_cents=30_000,
        )
        data = validate_success(
            api.get_renewal_quote(card["id"], SO),
            expected_status=200,
        )
        assert data.get("renewal_price_cents") == 30_000, (
            "PRD §3.7: lapsed → discount is zero → quote == price_cents."
        )
