"""Platform creation, defaults, and the deterministic clock.

PRD §3.1, §2.7.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DEFAULT_LATE_FEE_CENTS,
    DEFAULT_MAX_BORROWER_CONCENTRATION_BPS,
    DEFAULT_ORIGINATION_FEE_BPS,
    DEFAULT_SERVICING_FEE_BPS,
    advance_clock,
    advance_clock_payload,
    assert_platform,
    create_platform,
    create_platform_payload,
    get_platform,
    setup_platform_with_officer,
    validate_success,
)


class TestPlatformCreation:

    def test_platform_create_initializes_clock_to_zero(self, api):
        """PRD §3.1: "On creation, clock_day_index is initialized to 0."

        Claim: a newly created platform has clock_day_index == 0.
        """
        platform = create_platform()
        assert platform["clock_day_index"] == 0, (
            f"clock_day_index must be 0 on create, got "
            f"{platform['clock_day_index']}"
        )
        assert_platform(platform)

    def test_platform_default_origination_fee_bps_is_300(self, api):
        """PRD §3.1: "origination_fee_bps defaults to 300, which means
        three percent of principal will be deducted from the borrower's
        disbursement at origination".

        Claim: omitting origination_fee_bps on create -> server fills
        the default 300.
        """
        platform = create_platform()
        assert platform["origination_fee_bps"] == DEFAULT_ORIGINATION_FEE_BPS

    def test_platform_default_servicing_fee_bps_is_100(self, api):
        """PRD §3.1: "servicing_fee_bps defaults to 100, which on every
        interest distribution to investors will divert one percent of
        that scheduled interest as a servicing fee".
        """
        platform = create_platform()
        assert platform["servicing_fee_bps"] == DEFAULT_SERVICING_FEE_BPS

    def test_platform_default_late_fee_cents_is_2500(self, api):
        """PRD §3.1: "late_fee_cents defaults to 2500, the flat fee in
        cents assessed each time an installment becomes late".
        """
        platform = create_platform()
        assert platform["late_fee_cents"] == DEFAULT_LATE_FEE_CENTS

    def test_platform_default_max_borrower_concentration_is_1000(
        self, api,
    ):
        """PRD §3.1: "max_borrower_concentration_bps defaults to 1000,
        which caps any one investor's exposure to any one borrower at
        ten percent of that investor's committed capital".
        """
        platform = create_platform()
        assert (
            platform["max_borrower_concentration_bps"]
            == DEFAULT_MAX_BORROWER_CONCENTRATION_BPS
        )

    def test_platform_default_currency_is_usd(self, api):
        """PRD §3.1: "an optional ISO-4217 currency (defaulting to
        'USD')".

        Claim: omitting currency -> server fills "USD".
        """
        platform = create_platform()
        assert platform["currency"] == "USD"

    def test_platform_explicit_overrides_persisted(self, api):
        """PRD §3.1: optional economic parameters that govern every
        loan on the platform are persisted as supplied.

        Claim: an explicit value for each economic parameter is stored
        verbatim.
        """
        platform = create_platform(
            currency="EUR",
            origination_fee_bps=500,
            servicing_fee_bps=200,
            late_fee_cents=5000,
            max_borrower_concentration_bps=1500,
        )
        assert platform["currency"] == "EUR"
        assert platform["origination_fee_bps"] == 500
        assert platform["servicing_fee_bps"] == 200
        assert platform["late_fee_cents"] == 5000
        assert platform["max_borrower_concentration_bps"] == 1500


class TestClockAdvance:

    def test_clock_advance_by_positive_days(
        self, api, platform_operator_headers,
    ):
        """PRD §3.1: "It moves only when a PlatformOperator calls the
        advance-clock capability with a positive integer number of days
        ... the body parameter is named days and represents the count
        of logical days to advance."

        Claim: advance_clock with days=N increments clock_day_index by
        N.
        """
        platform, _ = setup_platform_with_officer()
        platform = advance_clock(platform["id"], 7)
        assert platform["clock_day_index"] == 7, (
            f"after advance 7 days, clock_day_index should be 7; "
            f"got {platform['clock_day_index']}"
        )
        platform = advance_clock(platform["id"], 10)
        assert platform["clock_day_index"] == 17, (
            f"after another 10 days, clock_day_index should be 17; "
            f"got {platform['clock_day_index']}"
        )
