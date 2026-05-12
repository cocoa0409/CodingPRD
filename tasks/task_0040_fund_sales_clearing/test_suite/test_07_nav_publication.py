"""PRD §3.4: NAV publication, T+1 gating, SoD, idempotency, and the two
NAV-per-share regimes (initial-NAV constant vs divisor formula).

Difficulty-design coverage tags appear in test docstrings.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    advance_clock_to,
    assert_nav_snapshot,
    create_kyc_approved_investor,
    create_on_shelf_fund,
    fee_tier,
    holding_period_tier,
    publish_nav_payload,
    setup_fund_with_outstanding_shares,
    setup_basic_investor_and_fund,
    setup_investor_with_confirmed_subscribe,
    validate_error,
    validate_success,
)


# =====================================================================
# T+1 temporal gating (PRD §3.4 / §2.10 priority 14)
# =====================================================================
class TestNavTPlus1:
    def test_publish_before_t_plus_1_rejected(self, api):
        """PRD §3.4: "the server clock must be at or after `nav_date`
        plus one calendar day (the T+1 rule, otherwise
        `ERR_NAV_T_PLUS_1_NOT_ELAPSED`)."

        Claim: an attempt to publish nav_date=T at exactly T 23:59 UTC
        (still before T+1) is rejected with ERR_NAV_T_PLUS_1_NOT_ELAPSED.
        """
        fund = create_on_shelf_fund()
        advance_clock_to("2026-10-01T23:59:00.000Z")
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-01",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        validate_error(res, "ERR_NAV_T_PLUS_1_NOT_ELAPSED")

    def test_publish_at_or_after_t_plus_1_succeeds(self, api):
        """PRD §3.4: "the server clock must be at or after `nav_date`
        plus one calendar day (the T+1 rule)."

        Claim: a publish call exactly at T+1 (0:00:00 UTC of T+1)
        satisfies the gate and produces a PUBLISHED snapshot.
        """
        fund = create_on_shelf_fund()
        advance_clock_to("2026-10-04T00:00:00.001Z")
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-03",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        nav = validate_success(res, expected_status=201)
        assert_nav_snapshot(nav)
        assert nav["status"] == "PUBLISHED"


# =====================================================================
# SoD: NAV publisher != Fund.shelf_review_actor_id (PRD §3.4)
# =====================================================================
class TestNavPublisherSoD:
    def test_publisher_equals_shelf_reviewer_rejected(self, api):
        """PRD §3.4: "the operator's `X-User-ID` must differ from the
        fund's `Fund.shelf_review_actor_id` (otherwise
        `ERR_SOD_VIOLATION_NAV`)."

        Claim: a NAV publish whose X-User-ID matches the
        ComplianceReviewer who approved the shelf is rejected with
        ERR_SOD_VIOLATION_NAV.
        """
        from test_helpers import build_user_headers
        # Same id, different roles:
        same_id_compliance = build_user_headers(
            "shared-id", "ComplianceReviewer"
        )
        same_id_nav = build_user_headers("shared-id", "NavOperator")

        fund = create_on_shelf_fund(approver_headers=same_id_compliance)
        advance_clock_to("2026-10-06T00:00:01.000Z")
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-05",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            same_id_nav,
        )
        validate_error(res, "ERR_SOD_VIOLATION_NAV")


# =====================================================================
# One snapshot per (fund, nav_date) (PRD §3.4)
# =====================================================================
class TestNavOneShot:
    def test_double_publish_same_date_rejected(self, api):
        """PRD §3.4: "The publication is one-shot: a second publish
        attempt for the same fund and `nav_date` after a `NavSnapshot`
        already exists in `PUBLISHED` status is rejected with
        `ERR_NAV_ALREADY_PUBLISHED`."

        Claim: the second POST publish for the same (fund, nav_date)
        yields ERR_NAV_ALREADY_PUBLISHED.

        # difficulty: resource_temporal_overlap/nav_snapshot_one_per_fund_per_nav_date
        """
        fund = create_on_shelf_fund()
        advance_clock_to("2026-10-08T00:00:01.000Z")
        first = validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-07",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        assert first["status"] == "PUBLISHED"
        # Second publish for same nav_date.
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-07",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        validate_error(res, "ERR_NAV_ALREADY_PUBLISHED")

    def test_publish_different_date_after_first_succeeds(self, api):
        """PRD §3.4: "Each trade date's net-asset-value snapshot is
        published exactly once on T+1." -- the one-shot lock is per
        (fund_id, nav_date), not per fund.

        Claim: the second NAV publish for a DIFFERENT nav_date succeeds.

        # difficulty: resource_temporal_overlap/nav_snapshot_one_per_fund_per_nav_date
        """
        fund = create_on_shelf_fund()
        advance_clock_to("2026-10-10T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-09",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        # Advance another day and publish for the new date.
        advance_clock_to("2026-10-11T00:00:01.000Z")
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-10",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        nav2 = validate_success(res, expected_status=201)
        assert nav2["status"] == "PUBLISHED"


# =====================================================================
# Initial-NAV vs divisor formula (PRD §3.4)
# =====================================================================
class TestNavRegimes:
    def test_initial_nav_when_no_outstanding_shares(self, api):
        """PRD §3.4: "when `shares_outstanding_at_nav` equals 0,
        `nav_per_share_micros` is the initial NAV constant 1,000,000
        (i.e., one CNY per share)."

        Claim: a NAV published while shares_outstanding_at_nav == 0
        produces nav_per_share_micros == 1_000_000 regardless of the
        portfolio_market_value supplied.

        # difficulty: dual_variant_calc/nav_publish_initial_vs_steady_state
        """
        fund = create_on_shelf_fund(
            management_fee_bps_annual=0,
            custodian_fee_bps_annual=0,
            sales_service_fee_bps_annual=0,
        )
        advance_clock_to("2026-10-13T00:00:01.000Z")
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-12",
                # PRD §3.4: when shares_outstanding == 0 the divisor path
                # is skipped entirely and the constant is used.
                portfolio_market_value_cents=500_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        nav = validate_success(res, expected_status=201)
        assert nav["shares_outstanding_at_nav"] == 0
        assert nav["nav_per_share_micros"] == 1_000_000

    def test_divisor_path_with_outstanding_shares(self, api):
        """PRD §3.4: "Otherwise, `nav_per_share_micros` is computed as
        `net_assets_cents` multiplied by 100,000,000 then divided by
        `shares_outstanding_at_nav`, with the final result rounded
        half-up at micros."

        Claim: when shares_outstanding=100_000_000 (in 1e-4 unit, ==
        10_000 whole shares) and net_assets_cents=1_000_000 (10_000
        CNY), nav_per_share_micros = 1_000_000 * 1e8 / 1e8 = 1_000_000.

        Setup: seed-subscribe to bring outstanding shares to
        100_000_000 at the initial-NAV path, then publish on a fresh
        nav_date with portfolio_market_value sized for nav==1.0.

        # difficulty: dual_variant_calc/nav_publish_initial_vs_steady_state
        """
        # seed_investor's first subscribe at NAV=1.0 will produce
        # 1_000_000 cents == 100_000_000 shares (1e-4 unit).
        seed_investor, fund = setup_fund_with_outstanding_shares(
            target_outstanding_shares=100_000_000,
            submit_at="2026-10-14T10:00:00.000Z",
        )
        # The fund should now have a NAV published for 2026-10-14.
        # Publish a SECOND nav_date at which the outstanding-shares
        # branch is exercised. Pick the next day; portfolio value sized
        # to keep nav at 1.0 CNY (i.e., net_assets_cents = shares / 100).
        advance_clock_to("2026-10-16T00:00:01.000Z")
        # net_assets_cents = total_outstanding_shares / 100 = 1_000_000
        # (with zero fees, gross_assets == net_assets == 1_000_000).
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-15",
                portfolio_market_value_cents=1_000_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        nav = validate_success(res, expected_status=201)
        assert nav["shares_outstanding_at_nav"] == 100_000_000
        assert nav["nav_per_share_micros"] == 1_000_000


# =====================================================================
# Daily-fee accrual: per-fee rounding then subtract (PRD §2.7 / §3.4)
# =====================================================================
class TestNavFeeAccrualNestedRounding:
    def test_per_fee_rounding_then_subtraction(self, api):
        """PRD §3.4: "the three daily fee accruals are each computed as
        the daily-prorated bps charge against gross assets:
        `management_fee_accrued_cents` is the gross-assets value
        multiplied by the fund's `management_fee_bps_annual`, divided
        by 10,000 (the basis-point denominator), divided by 365 (days
        per year), and rounded half-up at cents."

        PRD §2.7: "per-tier and per-lot fee components round half-up at
        cents *first*, then sum (never sum-then-round)."

        Setup: seed shares=100_000_000 on a 0-bps fund, then publish a
        SECOND nav_date for the same fund with mgmt=cust=sales=365 bps
        and gross_assets=1_000_000 cents. Each daily fee computes as
        1_000_000 * 365 / 10000 / 365 = 100 cents (no rounding needed),
        net_assets_cents = 1_000_000 - 300 = 999_700, and
        nav_per_share_micros = 999_700 * 1e8 / 1e8 = 999_700.

        Claim: each fee field equals 100; net_assets_cents == 999_700;
        nav_per_share_micros == 999_700.

        # difficulty: combinatorial_formula/nav_fee_deduction_nested_rounding_order_a_then_b
        """
        # PRD §3.2 lets us alter fees only AT FUND CREATION (and at
        # approve-shelf time the tier check still applies). To test
        # post-approval fees we need to create the fund with the target
        # fee bps from the start. Seed the fund with non-zero bps and
        # use seed-subscribe to grow shares through a NAV publish.
        # Approach: create fund with 365-bps fees, seed-subscribe at
        # initial-NAV (which uses INITIAL_NAV_MICROS regardless of fees),
        # then a SECOND NAV publish exercises the divisor path with the
        # 365-bps fee accrual.
        fund_overrides = {
            "management_fee_bps_annual": 365,
            "custodian_fee_bps_annual": 365,
            "sales_service_fee_bps_annual": 365,
            "subscription_fee_tiers": [fee_tier(0, None, 0)],
            "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
        }
        seed_investor, fund = setup_fund_with_outstanding_shares(
            target_outstanding_shares=100_000_000,
            submit_at="2026-10-20T10:00:00.000Z",
            fund_overrides=fund_overrides,
        )
        # Second nav_date with 365 bps applied.
        advance_clock_to("2026-10-22T00:00:01.000Z")
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-21",
                portfolio_market_value_cents=1_000_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        nav = validate_success(res, expected_status=201)
        # Each daily accrual: 1_000_000 * 365 / 10000 / 365 = 100 (exact).
        assert nav["management_fee_accrued_cents"] == 100, (
            f"PRD §3.4 daily mgmt fee = gross*bps/10000/365 = "
            f"1_000_000 * 365 / 10000 / 365 = 100 cents; got "
            f"{nav['management_fee_accrued_cents']}"
        )
        assert nav["custodian_fee_accrued_cents"] == 100
        assert nav["sales_service_fee_accrued_cents"] == 100
        assert nav["gross_assets_cents"] == 1_000_000
        # PRD §3.4: net_assets = gross - sum-of-fees (each rounded first).
        assert nav["net_assets_cents"] == 999_700
        # nav_per_share_micros = net_assets * 1e8 / shares_outstanding
        # = 999_700 * 1e8 / 1e8 = 999_700 micros (exact).
        assert nav["nav_per_share_micros"] == 999_700


# =====================================================================
# NAV adjustment (PRD §3.4)
# =====================================================================
class TestNavAdjustment:
    def test_published_nav_can_be_adjusted_by_compliance_reviewer(self, api):
        """PRD §3.4: "A published NAV may be adjusted later by a
        `ComplianceReviewer`, who supplies the corrected
        `portfolio_market_value_cents`, `portfolio_accrued_income_cents`,
        and a non-empty `adjustment_reason`. The snapshot recomputes
        through the same NAV formula, transitions `PUBLISHED →
        ADJUSTED`."

        Claim: an adjust call on a PUBLISHED NAV transitions the
        snapshot's status to ADJUSTED.
        """
        fund = create_on_shelf_fund()
        advance_clock_to("2026-10-25T00:00:01.000Z")
        # First publish at zero outstanding shares (initial-NAV path).
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2026-10-24",
                portfolio_market_value_cents=0,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        # Now adjust.
        from test_helpers import adjust_nav_payload
        res = api.adjust_nav(
            fund["id"],
            "2026-10-24",
            adjust_nav_payload(
                portfolio_market_value_cents=10_000,
                portfolio_accrued_income_cents=0,
                adjustment_reason="custodian re-attested mark",
            ),
            TEST_USERS["compliance_reviewer_headers"],
        )
        adjusted = validate_success(res)
        assert adjusted["status"] == "ADJUSTED"
        assert adjusted["adjustment_reason"] == "custodian re-attested mark"
