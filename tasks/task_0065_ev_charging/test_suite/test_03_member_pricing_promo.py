"""Member, wallet, PricingVersion overlap, ToU window overlap, and
PromoActivity rules.

PRD §3.2 (Members, Wallets, and Pricing Versions).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_member,
    assert_pricing_version,
    assert_promo_activity,
    create_member,
    create_platform_operator_row,
    create_pricing_version,
    create_promo_activity,
    credit_wallet,
    hhmm_window,
    iso_day,
    validate_error,
    validate_success,
    PO,
)


# ===========================================================================
# Member create / wallet credit
# ===========================================================================
class TestMemberCreation:
    """PRD §3.2: 'A Member carries a display_name ... a home_operator_id
    ... a tier of BASIC, SILVER, GOLD, or PLATINUM defaulting to
    BASIC.'"""

    def test_create_member_default_tier_is_basic(self, api):
        """PRD §3.2: 'a tier of BASIC, SILVER, GOLD, or PLATINUM
        defaulting to BASIC.'"""
        operator = create_platform_operator_row()
        from test_helpers import create_member_payload
        res = api.create_member(
            create_member_payload(home_operator_id=operator["id"]),
            PO,
        )
        body = validate_success(res, expected_status=201)
        assert_member(body)
        assert body["tier"] == "BASIC"

    def test_wallet_credit_increases_balance(self, api):
        """PRD §3.2: 'Wallet credits ... increase wallet_balance_cents
        by a supplied amount_cents.'"""
        operator = create_platform_operator_row()
        member = create_member(home_operator_id=operator["id"])
        assert member["wallet_balance_cents"] == 0
        updated = credit_wallet(
            member_id=member["id"], amount_cents=2500,
        )
        assert updated["wallet_balance_cents"] == 2500


# ===========================================================================
# PricingVersion window overlap (PRD §3.2)
# ===========================================================================
class TestPricingVersionOverlap:
    """PRD §3.2: 'the new interval must not overlap any other pricing
    version owned by the same operator on a half-open [effective_from,
    effective_to) basis — if any overlap exists the request is rejected
    with ERR_PRICING_WINDOW_OVERLAP.'"""

    def test_overlapping_window_for_same_operator_rejected(self, api):
        operator = create_platform_operator_row()
        create_pricing_version(
            operator_id=operator["id"],
            effective_from=iso_day(2026, 5, 1),
            effective_to=iso_day(2026, 6, 1),
        )
        from test_helpers import create_pricing_version_payload
        # New window strictly overlaps May 1..Jun 1.
        res = api.create_pricing_version(
            create_pricing_version_payload(
                operator_id=operator["id"],
                effective_from=iso_day(2026, 5, 15),
                effective_to=iso_day(2026, 7, 1),
            ),
            PO,
        )
        validate_error(res, ApiErrorId.ERR_PRICING_WINDOW_OVERLAP.value)

    def test_adjacent_windows_are_allowed(self, api):
        """PRD §3.2: '[effective_from, effective_to)' half-open — so
        A.effective_to == B.effective_from is non-overlapping (the
        instant belongs to B alone)."""
        operator = create_platform_operator_row()
        create_pricing_version(
            operator_id=operator["id"],
            effective_from=iso_day(2026, 5, 1),
            effective_to=iso_day(2026, 6, 1),
        )
        from test_helpers import create_pricing_version_payload
        res = api.create_pricing_version(
            create_pricing_version_payload(
                operator_id=operator["id"],
                effective_from=iso_day(2026, 6, 1),
                effective_to=iso_day(2026, 7, 1),
            ),
            PO,
        )
        body = validate_success(res, expected_status=201)
        assert_pricing_version(body)

    def test_distinct_operator_same_window_allowed(self, api):
        """PRD §3.2: overlap rule is scoped to 'the same operator'."""
        op_a = create_platform_operator_row()
        op_b = create_platform_operator_row()
        create_pricing_version(
            operator_id=op_a["id"],
            effective_from=iso_day(2026, 5, 1),
            effective_to=iso_day(2026, 6, 1),
        )
        # Same window on a different operator — must succeed.
        from test_helpers import create_pricing_version_payload
        res = api.create_pricing_version(
            create_pricing_version_payload(
                operator_id=op_b["id"],
                effective_from=iso_day(2026, 5, 1),
                effective_to=iso_day(2026, 6, 1),
            ),
            PO,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# Peak / valley windows overlap (PRD §3.2)
# ===========================================================================
class TestTouWindowsOverlap:
    """PRD §3.2: 'the supplied peak and valley window arrays must not
    overlap each other — if they do, the request is rejected with
    ERR_TOU_WINDOWS_OVERLAP.'"""

    def test_peak_and_valley_window_overlap_rejected(self, api):
        operator = create_platform_operator_row()
        from test_helpers import create_pricing_version_payload
        res = api.create_pricing_version(
            create_pricing_version_payload(
                operator_id=operator["id"],
                effective_from=iso_day(2026, 1, 1),
                effective_to=iso_day(2027, 1, 1),
                peak_windows=[hhmm_window("08:00", "12:00")],
                valley_windows=[hhmm_window("11:00", "14:00")],
            ),
            PO,
        )
        validate_error(res, ApiErrorId.ERR_TOU_WINDOWS_OVERLAP.value)

    def test_peak_and_valley_windows_non_overlapping_accepted(self, api):
        operator = create_platform_operator_row()
        from test_helpers import create_pricing_version_payload
        res = api.create_pricing_version(
            create_pricing_version_payload(
                operator_id=operator["id"],
                effective_from=iso_day(2026, 1, 1),
                effective_to=iso_day(2027, 1, 1),
                peak_windows=[hhmm_window("08:00", "11:00")],
                valley_windows=[hhmm_window("12:00", "14:00")],
            ),
            PO,
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# PromoActivity
# ===========================================================================
class TestPromoActivity:
    """PRD §3.2: 'Each promo has a name ... inclusive starts_at and
    exclusive ends_at (with ends_at strictly greater than starts_at), a
    service_fee_discount_bps between zero and five thousand inclusive
    ..., and an applies_to_tiers list — a non-empty subset of {BASIC,
    SILVER, GOLD, PLATINUM}.'"""

    def test_create_promo_activity_succeeds(self, api):
        operator = create_platform_operator_row()
        promo = create_promo_activity(
            operator_id=operator["id"],
            starts_at=iso_day(2026, 1, 1),
            ends_at=iso_day(2027, 1, 1),
            service_fee_discount_bps=500,
            applies_to_tiers=["SILVER", "GOLD"],
        )
        assert_promo_activity(promo)
        assert promo["service_fee_discount_bps"] == 500
        assert promo["applies_to_tiers"] == ["SILVER", "GOLD"]
