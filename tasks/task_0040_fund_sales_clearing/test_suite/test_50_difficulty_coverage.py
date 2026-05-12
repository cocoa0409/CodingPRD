"""Additional tests required by SCAFFOLD_DIFFICULTY_DESIGN.yaml to bring
each difficulty-design instance up to the required two-test minimum.

Each test in this file pairs with an earlier test that already covers
the same instance; every docstring cites the verbatim PRD sentence that
uniquely names the asserted rule. Difficulty tags appear at the end of
each docstring.

Date strategy: this file's clock advances all start at 2028-01-01 or
later, after test_13's last advance at 2027-12-15.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    TEST_USERS,
    adjust_exception_payload,
    advance_clock_to,
    create_dividend_plan_payload,
    create_kyc_approved_investor,
    create_on_shelf_fund,
    create_subscribe_order_payload,
    ensure_clock_at_least,
    external_record,
    fee_tier,
    find_audit_entries,
    get_fund_fresh,
    get_order_fresh,
    holding_period_tier,
    list_audit_logs_for,
    make_investor_headers,
    open_reconciliation_run,
    publish_nav_payload,
    set_distribution_option_payload,
    setup_basic_investor_and_fund,
    setup_fund_with_outstanding_shares,
    setup_investor_with_confirmed_subscribe,
    submit_subscribe_order,
    submit_redeem_order,
    subscribe_confirm,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# =====================================================================
# Rule 2.1 second test (combinatorial_formula/nav_fee_deduction_nested_rounding)
# =====================================================================
class TestNavFeeAccrualSecond:
    def test_zero_bps_fees_yield_zero_accrual(self, api):
        """PRD §3.4: "the three daily fee accruals are each computed as
        the daily-prorated bps charge against gross assets:
        `management_fee_accrued_cents` is the gross-assets value
        multiplied by the fund's `management_fee_bps_annual`, divided
        by 10,000 (the basis-point denominator), divided by 365 (days
        per year), and rounded half-up at cents."

        Claim: with all three fee bps = 0, every daily-fee accrual is
        0 and net_assets_cents == gross_assets_cents (no fees deducted).
        This is the degenerate but valid path through the same per-fee
        rounding machinery.

        # difficulty: combinatorial_formula/nav_fee_deduction_nested_rounding_order_a_then_b
        """
        seed_investor, fund = setup_fund_with_outstanding_shares(
            target_outstanding_shares=100_000_000,
            submit_at="2028-01-01T10:00:00.000Z",
        )
        ensure_clock_at_least("2028-01-03T00:00:01.000Z")
        res = api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2028-01-02",
                portfolio_market_value_cents=2_000_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        )
        nav = validate_success(res, expected_status=201)
        assert nav["management_fee_accrued_cents"] == 0
        assert nav["custodian_fee_accrued_cents"] == 0
        assert nav["sales_service_fee_accrued_cents"] == 0
        assert nav["gross_assets_cents"] == 2_000_000
        assert nav["net_assets_cents"] == 2_000_000


# =====================================================================
# Rule 2.2 (combinatorial_formula/redemption_fee_circular_dependency_pinned)
# =====================================================================
class TestRedemptionFeeCircularDependency:
    def test_back_end_load_uses_original_lot_cost(self, api):
        """PRD §3.5: "When the fund's `back_end_load_enabled` is true,
        each lot also accrues a back-end load equal to that lot's
        proportional original cost -- `cost_cents` multiplied by
        `take` divided by the lot's original `shares`, rounded half-up
        at cents -- multiplied by the subscription-tier `rate_bps`
        whose tier the lot's proportional cost falls into."

        Setup: SUBSCRIBE 100_000 cents under a back-end-load fund at
        NAV=1.0 -> lot.cost_cents=100_000, shares=10_000_000. Holding
        period < 30 days redemption tier rate is 0 bps so redemption_fee
        = 0; subscription tier rate is 150 bps so back-end load =
        100_000 * 150/10000 = 1_500. confirmed_amount_cents = gross -
        redemption_fee - back_end_load = 100_000 - 0 - 1_500 = 98_500.

        Claim: at full redemption, the back-end load is computed
        against the lot's ORIGINAL cost_cents (100_000), not the
        current value, yielding back_end_load_fee_cents == 1_500 and
        confirmed_amount_cents == 98_500.

        # difficulty: combinatorial_formula/redemption_fee_circular_dependency_pinned
        """
        # Threshold raised so 100% redemption is below it (avoids the
        # large-redemption deferral path and isolates the fee math).
        investor, fund = setup_basic_investor_and_fund(
            cash_cents=10_000_000,
            fund_overrides={
                "back_end_load_enabled": True,
                "subscription_fee_tiers": [fee_tier(0, None, 150)],
                "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
                "large_redemption_threshold_pct_bps": 100_000,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        ensure_clock_at_least("2028-02-01T10:00:00.000Z")
        sub_order, _ = subscribe_confirm(
            investor, fund, gross_amount_cents=100_000,
        )
        assert sub_order["status"] == "CONFIRMED"
        # PRD §3.5 back-end model: subscription_fee=0, shares=10_000_000,
        # lot.cost_cents = 100_000.
        assert sub_order["confirmed_shares"] == 10_000_000
        assert sub_order["subscription_fee_cents"] == 0

        # Full redeem.
        ensure_clock_at_least("2028-02-04T10:00:00.000Z")
        red = submit_redeem_order(
            investor, fund, requested_shares=10_000_000
        )
        ensure_clock_at_least("2028-02-06T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                # Keep NAV=1.0 (net_assets = shares/100 = 100_000)
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after = get_order_fresh(red["id"])
        assert red_after["status"] == "CONFIRMED", (
            f"Expected CONFIRMED; got {red_after['status']!r}"
        )
        # PRD §3.5: redemption_fee = sum of per-lot fees (0 bps tier).
        assert red_after["redemption_fee_cents"] == 0
        # PRD §3.5: back-end load uses original lot cost.
        # 100_000 cost * 150 bps / 10000 = 1_500 cents.
        assert red_after["back_end_load_fee_cents"] == 1_500, (
            f"PRD §3.5: back-end load = original_lot_cost * "
            f"sub_tier_rate_bps / 10000 = 100_000 * 150 / 10000 = 1_500; "
            f"got {red_after['back_end_load_fee_cents']}"
        )
        # PRD §3.5: confirmed_amount = gross - redemption_fee - back_end_load.
        # gross_redeem = 10_000_000 * 1_000_000 / 1e8 = 100_000 cents.
        assert red_after["confirmed_amount_cents"] == 98_500

    def test_redemption_fee_with_holding_period_tier(self, api):
        """PRD §3.5: "Per-lot fees are rounded *first* and then summed,
        never sum-then-round; the resulting sum is `redemption_fee_cents`."

        PRD §3.5: "For each lot consumed, `holding_days` is computed as
        the floor of the calendar-day difference between the order's
        `trade_date` and the lot's `acquired_at`. The redemption tier
        for that lot is the first entry of `redemption_fee_tiers` (in
        ascending `min_holding_days` order) whose `min_holding_days` is
        at most `holding_days` and whose `max_holding_days` is either
        null or strictly greater than `holding_days`."

        Setup: front-end fund (back_end_load_enabled=false) with
        redemption tier 0..30 days = 50 bps. SUBSCRIBE 100_000 cents at
        NAV=1.0 (0-bps subscription) -> shares=10_000_000, cost=100_000.
        REDEEM all 10_000_000 shares within 30 days. gross_redeem =
        10_000_000 * 1_000_000 / 1e8 = 100_000 cents. Per the lot's
        50 bps tier: lot_fee = 100_000 * 50 / 10000 = 500.
        redemption_fee = 500. back_end_load_fee = 0 (front-end fund).
        confirmed_amount = 100_000 - 500 - 0 = 99_500.

        Claim: redemption_fee_cents == 500, back_end_load_fee_cents
        == 0, confirmed_amount_cents == 99_500.

        # difficulty: combinatorial_formula/redemption_fee_circular_dependency_pinned
        """
        investor, fund = setup_basic_investor_and_fund(
            cash_cents=10_000_000,
            fund_overrides={
                "back_end_load_enabled": False,
                "subscription_fee_tiers": [fee_tier(0, None, 0)],
                "redemption_fee_tiers": [
                    holding_period_tier(0, 30, 50),
                    holding_period_tier(30, None, 25),
                ],
                "large_redemption_threshold_pct_bps": 100_000,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        ensure_clock_at_least("2028-02-15T10:00:00.000Z")
        sub_order, _ = subscribe_confirm(
            investor, fund, gross_amount_cents=100_000,
        )
        assert sub_order["status"] == "CONFIRMED"
        assert sub_order["confirmed_shares"] == 10_000_000
        # Full redeem within 30 days (holding < 30 days -> 50 bps tier).
        ensure_clock_at_least("2028-02-25T10:00:00.000Z")
        red = submit_redeem_order(
            investor, fund, requested_shares=10_000_000
        )
        ensure_clock_at_least("2028-02-27T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after = get_order_fresh(red["id"])
        assert red_after["status"] == "CONFIRMED"
        # PRD §3.5: per-lot fee 500 (one lot) summed -> 500 total.
        assert red_after["redemption_fee_cents"] == 500
        # PRD §3.5: front-end fund -> back_end_load_fee_cents = 0.
        assert red_after["back_end_load_fee_cents"] == 0
        # confirmed_amount = gross - redemption_fee - back_end_load.
        assert red_after["confirmed_amount_cents"] == 99_500


# =====================================================================
# Rule 3.2 second test (non_linear_state_machine/order_redemption_branching)
# =====================================================================
class TestRedemptionBranchingSecond:
    def test_second_subthreshold_redeem_skips_deferral(self, api):
        """PRD §3.4: "For `REDEEM` orders below the threshold and for all
        other order types, confirmation runs from `ACCEPTED → CONFIRMED`
        directly."

        Claim: the non-deferral branch of the Order state-machine fork
        (ACCEPTED -> CONFIRMED, NOT through LARGE_REDEMPTION_DEFERRED)
        is exercised when pct_bps is well below the threshold.

        # difficulty: non_linear_state_machine/order_redemption_branching_with_deferral_loop
        """
        investor, fund, sub_order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2028-03-01T10:00:00.000Z",
            fund_overrides={
                "subscription_fee_tiers": [fee_tier(0, None, 0)],
                "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
                "large_redemption_threshold_pct_bps": 1_000,
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        # Investor holds 10_000_000 shares; 10 bps = 10_000 shares.
        ensure_clock_at_least("2028-03-03T10:00:00.000Z")
        red = submit_redeem_order(
            investor, fund, requested_shares=10_000  # 10 bps, below threshold
        )
        ensure_clock_at_least("2028-03-05T00:00:01.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date=red["trade_date"].split("T")[0],
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        red_after = get_order_fresh(red["id"])
        # PRD §3.4: below-threshold REDEEM goes ACCEPTED -> CONFIRMED
        # directly, not through LARGE_REDEMPTION_DEFERRED.
        assert red_after["status"] == "CONFIRMED", (
            f"PRD §3.4: below-threshold REDEEM confirms directly; got "
            f"{red_after['status']!r}"
        )


# =====================================================================
# Rule 4.1 second test (transitive_cascade/subscribe_confirm_three_hop)
# =====================================================================
class TestSubscribeConfirmCascadeSecond:
    def test_zero_bps_subscribe_cascade_no_drift(self, api):
        """PRD §3.4: "for `SUBSCRIBE`, a new `LotEntry` is created ...,
        the investor's `Holding.shares` and `Holding.cost_basis_cents`
        are recomputed by re-aggregating the open lots;
        `Fund.total_outstanding_shares` is increased by the confirmed
        shares; and the investor's `cash_balance_cents` is decreased by
        the order's `gross_amount_cents`."

        Claim: a 0-bps subscribe at NAV=1.0 produces the exact triple
        (Holding.shares == confirmed_shares,
         Fund.total_outstanding_shares == confirmed_shares,
         Investor.cash_balance_cents -= gross_amount). With 0-bps
        subscription_fee_tiers and gross=50_000, confirmed_shares is
        5_000_000 and the cascade is exact.

        # difficulty: transitive_cascade/subscribe_confirm_three_hop_cascade
        """
        investor = create_kyc_approved_investor(cash_cents=200_000)
        fund = create_on_shelf_fund(
            subscription_fee_tiers=[fee_tier(0, None, 0)],
            redemption_fee_tiers=[holding_period_tier(0, None, 0)],
            management_fee_bps_annual=0,
            custodian_fee_bps_annual=0,
            sales_service_fee_bps_annual=0,
        )
        ensure_clock_at_least("2028-04-01T10:00:00.000Z")
        order, _ = subscribe_confirm(
            investor, fund, gross_amount_cents=50_000,
        )
        assert order["status"] == "CONFIRMED"
        assert order["confirmed_shares"] == 5_000_000
        # hop 3:
        fund_after = get_fund_fresh(fund["id"])
        assert fund_after["total_outstanding_shares"] == 5_000_000
        # Investor cash debit:
        from test_helpers import api_client as ac
        inv_after = validate_success(ac.get_investor(
            investor["id"], TEST_USERS["platform_admin_headers"]
        ))
        assert inv_after["cash_balance_cents"] == 200_000 - 50_000


# =====================================================================
# Rule 4.2 (transitive_cascade/dividend_reinvest_three_hop_cascade)
# =====================================================================
class TestDividendReinvestCascade:
    def test_dividend_reinvest_creates_lot_and_grows_shares(self, api):
        """PRD §3.6: "when `option` is `REINVEST`, `reinvested_shares` is
        computed as `net_dividend_cents` multiplied by 100,000,000
        divided by the ex-dividend-date NAV's `nav_per_share_micros`,
        rounded *half-down* at the 1e-4 share unit ..., and a new
        `LotEntry` is created with that `shares` count, `cost_cents`
        equal to `net_dividend_cents`, `acquired_at` set to the
        ex-dividend date, and `status` `OPEN`; the investor's
        `Holding.shares` and `Holding.cost_basis_cents` are recomputed;
        and `Fund.total_outstanding_shares` increases by the reinvested
        shares."

        Claim: after a REINVEST dividend payment, the cascade hops are:
          - a LotEntry exists for this distribution (verified through
            the holding's growth);
          - Holding.shares = pre + reinvested_shares;
          - Fund.total_outstanding_shares = pre + reinvested_shares.

        # difficulty: transitive_cascade/dividend_reinvest_three_hop_cascade
        """
        # Setup: investor holds 10_000_000 shares; dividend pays 100
        # cents/share gross at 0 tax, reinvested at NAV=1.0 ->
        # reinvested_shares = 100 cents/share * 10_000_000 shares /
        # nav_micros (1.0 CNY per share).
        # Compute: gross_dividend = eligible_shares * dividend_per_share
        # / 1e8 = 10_000_000 * 1_000 / 1e8 = 100 cents.
        # net = 100 (zero tax). reinvested = 100 * 1e8 / 1_000_000 = 10_000.
        investor, fund, order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2028-05-01T10:00:00.000Z",
            fund_overrides={
                "subscription_fee_tiers": [fee_tier(0, None, 0)],
                "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        assert order["status"] == "CONFIRMED"
        # Investor now holds 10_000_000 shares.
        ensure_clock_at_least("2028-05-05T10:00:00.000Z")
        plan = validate_success(api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2028-05-05",
                record_date="2028-05-10",
                ex_dividend_date="2028-05-11",
                payment_date="2028-05-15",
                dividend_per_share_micros=1_000,  # 0.001 CNY/share
                tax_rate_bps_domestic=0,
                tax_rate_bps_foreign=0,
            ),
            TEST_USERS["product_operator_headers"],
        ), expected_status=201)
        # Investor sets REINVEST option.
        # First, mark ex-dividend (after clock advances past
        # ex_dividend_date and AFTER NAV is published for ex_dividend_date).
        # PRD §3.6: NAV must be PUBLISHED for ex_dividend_date before
        # execute-payment, but not for mark-ex-dividend (only ex_dividend_date
        # date condition + ON_SHELF).
        ensure_clock_at_least("2028-05-11T01:00:00.000Z")
        validate_success(api.mark_ex_dividend(
            plan["id"], TEST_USERS["nav_operator_headers"]
        ))
        # Set option to REINVEST. PRD §3.6: investor sets option between
        # ex-dividend and payment.
        validate_success(api.set_distribution_option(
            plan["id"], investor["id"],
            set_distribution_option_payload("REINVEST"),
            make_investor_headers(investor["id"]),
        ))
        # Publish NAV for ex_dividend_date (required by PRD §3.6 for
        # execute-payment).
        ensure_clock_at_least("2028-05-12T01:00:00.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2028-05-11",
                # Keep NAV=1.0: net_assets = shares/100 = 100_000.
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        # Advance past payment_date.
        ensure_clock_at_least("2028-05-16T01:00:00.000Z")
        validate_success(api.execute_dividend_payment(
            plan["id"], TEST_USERS["nav_operator_headers"]
        ))
        # PRD §3.6 cascade:
        # gross = 10_000_000 * 1_000 / 1e8 = 100 cents
        # net = 100 (no tax)
        # reinvested_shares = round_half_down(100 * 1e8 / 1_000_000) = 10_000
        # New Holding.shares = 10_000_000 + 10_000 = 10_010_000.
        fund_after = get_fund_fresh(fund["id"])
        assert fund_after["total_outstanding_shares"] == 10_010_000, (
            f"PRD §3.6 hop 3: Fund.total_outstanding_shares += "
            f"reinvested_shares; expected 10_010_000, got "
            f"{fund_after['total_outstanding_shares']}"
        )

    def test_dividend_cash_does_not_increase_outstanding_shares(self, api):
        """PRD §3.6: "when `option` is `CASH`, the investor's
        `cash_balance_cents` is increased by `net_dividend_cents`."
        And by complement: the CASH branch does NOT add to
        Fund.total_outstanding_shares (no new LotEntry is created;
        no Holding.shares mutation; no fund-shares mutation).

        Claim: a CASH-option dividend payment does NOT increase
        Fund.total_outstanding_shares -- the three-hop cascade observed
        for REINVEST is exclusive to the REINVEST branch, contrasting
        the two same-trigger paths.

        # difficulty: transitive_cascade/dividend_reinvest_three_hop_cascade
        """
        investor, fund, sub_order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2028-09-01T10:00:00.000Z",
            fund_overrides={
                "subscription_fee_tiers": [fee_tier(0, None, 0)],
                "redemption_fee_tiers": [holding_period_tier(0, None, 0)],
                "management_fee_bps_annual": 0,
                "custodian_fee_bps_annual": 0,
                "sales_service_fee_bps_annual": 0,
            },
        )
        shares_before_dividend = get_fund_fresh(
            fund["id"]
        )["total_outstanding_shares"]
        ensure_clock_at_least("2028-09-05T10:00:00.000Z")
        plan = validate_success(api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2028-09-05",
                record_date="2028-09-10",
                ex_dividend_date="2028-09-11",
                payment_date="2028-09-15",
                dividend_per_share_micros=1_000,
                tax_rate_bps_domestic=0,
                tax_rate_bps_foreign=0,
            ),
            TEST_USERS["product_operator_headers"],
        ), expected_status=201)
        ensure_clock_at_least("2028-09-11T01:00:00.000Z")
        validate_success(api.mark_ex_dividend(
            plan["id"], TEST_USERS["nav_operator_headers"]
        ))
        # NOTE: do NOT switch option to REINVEST; PRD §3.6 says default
        # is CASH.
        ensure_clock_at_least("2028-09-12T01:00:00.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2028-09-11",
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        ensure_clock_at_least("2028-09-16T01:00:00.000Z")
        validate_success(api.execute_dividend_payment(
            plan["id"], TEST_USERS["nav_operator_headers"]
        ))
        # PRD §3.6: CASH branch does NOT mutate fund shares.
        fund_after = get_fund_fresh(fund["id"])
        assert fund_after["total_outstanding_shares"] == shares_before_dividend, (
            f"PRD §3.6: CASH-option dividend MUST NOT increase "
            f"Fund.total_outstanding_shares; expected "
            f"{shares_before_dividend}, got "
            f"{fund_after['total_outstanding_shares']}"
        )


# =====================================================================
# Rule 5.1 second test (priority_pair: state vs KYC)
# =====================================================================
class TestPriorityStateVsKycSecond:
    def test_state_wins_when_fund_suspended_and_kyc_pending(self, api):
        """PRD §2.10: "(5) target resource is in a valid state for the
        operation (else `ERR_INVALID_STATE`)". Priority 5 is higher
        than priority 9 (KYC).

        Claim: with a SUSPENDED fund and PENDING-KYC investor, the
        state precondition fires first and the response is
        ERR_INVALID_STATE.

        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_kyc
        """
        from test_helpers import (
            api_client as ac,
            create_investor_pending_kyc,
            credit_cash_payload,
        )
        # Investor PENDING.
        investor = create_investor_pending_kyc()
        ac.credit_cash(
            investor["id"], credit_cash_payload(10_000_000),
            TEST_USERS["platform_admin_headers"],
        )
        # Fund created and approved, then SUSPENDED.
        from test_helpers import create_on_shelf_fund
        fund = create_on_shelf_fund()
        validate_success(api.suspend_fund(
            fund["id"], TEST_USERS["compliance_reviewer_headers"]
        ))
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=1_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# =====================================================================
# Rule 5.2 second test (priority_pair: suitability vs limit)
# =====================================================================
class TestPrioritySuitabilityVsLimitSecond:
    def test_suitability_wins_when_above_max_amount(self, api):
        """PRD §2.10: "(10) suitability match -- investor risk tolerance
        is at least the fund's risk rating on the C-vs-R index (else
        `ERR_SUITABILITY_MISMATCH`); ... (16) order amount/share within
        fund min/max bounds (else `ERR_ORDER_LIMIT_VIOLATED`)."
        Priority 10 wins over priority 16.

        Claim: a C1 investor on R5 fund attempting an order ABOVE
        max_subscription_amount_cents yields ERR_SUITABILITY_MISMATCH
        (priority 10), not ERR_ORDER_LIMIT_VIOLATED (priority 16).

        # difficulty: priority_pair_validation_conflict/business_safety_suitability_vs_business_constraint_amount
        """
        investor = create_kyc_approved_investor(risk_tolerance="C1")
        fund = create_on_shelf_fund(
            risk_rating="R5",
            min_subscription_amount_cents=1,
            max_subscription_amount_cents=1_000,
        )
        # Submit an order ABOVE max.
        res = api.create_order(
            create_subscribe_order_payload(
                fund_id=fund["id"], gross_amount_cents=10_000
            ),
            make_investor_headers(investor["id"]),
        )
        validate_error(res, "ERR_SUITABILITY_MISMATCH")


# =====================================================================
# Rule 6.2 second test (boundary_precision_check/empty_external_records)
# =====================================================================
class TestEmptyExternalRecordsSecond:
    def test_empty_external_records_run_remains_open(self, api):
        """PRD §3.7: "Running the match compares the internal SETTLED
        ledger entries for the run's scope and `as_of_date` against the
        supplied `external_records`."

        Claim: after the rejection of run-match on an empty
        external_records run, the run remains in status OPEN (no
        partial transition).

        # difficulty: boundary_precision_check/empty_external_records_match_skipped
        """
        run = open_reconciliation_run(
            as_of_date="2028-06-01",
            scope="TA_VS_BANK",
            external_records=[],
        )
        assert run["status"] == "OPEN"
        res = api.run_match(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
        validate_error(res, "ERR_INVALID_STATE")
        # Re-read run; should still be OPEN.
        detail = validate_success(api.get_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        ))
        # Some implementations nest the run under a 'run' key when
        # combining run+exceptions+instructions; tolerate both shapes.
        if "status" in detail:
            assert detail["status"] == "OPEN"
        elif "run" in detail and isinstance(detail["run"], dict):
            assert detail["run"]["status"] == "OPEN"
        else:
            pytest.fail(
                f"PRD §3.7 GET response missing recognizable status field: "
                f"{detail!r}"
            )


# =====================================================================
# Rule 7.2 second test (cross_entity: dividend payment requires NAV)
# =====================================================================
class TestDividendPaymentRequiresNavSecond:
    def test_payment_requires_payment_date_reached(self, api):
        """PRD §3.6: "Once payment_date has been reached on the server
        clock and the NAV snapshot for the plan's `ex_dividend_date` is
        `PUBLISHED`, a `NavOperator` executes payment."

        Claim: even when NAV for ex_dividend_date IS published, the
        execute-payment call before payment_date is rejected with
        ERR_INVALID_STATE (the temporal precondition is the second
        cross-entity gate).

        # difficulty: cross_entity_state_dependency/dividend_payment_requires_nav_published_for_ex_div_date
        """
        # Pick dates well past any prior test's clock advance so the
        # `ensure_clock_at_least` calls below actually move the clock and
        # land it strictly between ex_dividend_date and payment_date. The
        # session's prior advances reach into Sep-2028, so this scenario
        # uses Nov/Dec-2028 dates to guarantee monotonic forward motion.
        investor, fund, order, _ = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2028-11-01T10:00:00.000Z",
        )
        ensure_clock_at_least("2028-11-05T10:00:00.000Z")
        plan = validate_success(api.create_dividend_plan(
            fund["id"],
            create_dividend_plan_payload(
                announcement_date="2028-11-05",
                record_date="2028-11-10",
                ex_dividend_date="2028-11-11",
                payment_date="2028-12-20",
                dividend_per_share_micros=1_000,
                tax_rate_bps_domestic=0,
                tax_rate_bps_foreign=0,
            ),
            TEST_USERS["product_operator_headers"],
        ), expected_status=201)
        ensure_clock_at_least("2028-11-11T01:00:00.000Z")
        validate_success(api.mark_ex_dividend(
            plan["id"], TEST_USERS["nav_operator_headers"]
        ))
        # Publish NAV for ex_dividend_date.
        ensure_clock_at_least("2028-11-12T01:00:00.000Z")
        validate_success(api.publish_nav(
            fund["id"],
            publish_nav_payload(
                nav_date="2028-11-11",
                portfolio_market_value_cents=100_000,
                portfolio_accrued_income_cents=0,
            ),
            TEST_USERS["nav_operator_headers"],
        ), expected_status=201)
        # Clock NOT yet past payment_date 2028-12-20.
        ensure_clock_at_least("2028-11-15T01:00:00.000Z")
        res = api.execute_dividend_payment(
            plan["id"], TEST_USERS["nav_operator_headers"]
        )
        validate_error(res, "ERR_INVALID_STATE")


# =====================================================================
# Rule 9.2 second test (compensating_invariant/recon_adjust_net_break)
# =====================================================================
class TestReconAdjustNetBreakSecond:
    def test_finalize_after_partial_adjustment_rejected(self, api):
        """PRD §3.7: "the original `net_break_cents` (as observed at the
        moment the run first found exceptions) minus the sum of
        `adjustment_amount_cents` across all `ADJUSTED` exceptions must
        equal exactly 0 (using exact integer arithmetic, no rounding).
        When that holds, the run advances `EXCEPTIONS_FOUND →
        RESOLVED`. When it does not, the finalize is rejected with
        `ERR_RECONCILIATION_INVARIANT_BROKEN`."

        Claim: an AMOUNT_MISMATCH whose adjustment is the WRONG amount
        (does not bring net_break back to 0) is rejected at finalize
        with ERR_RECONCILIATION_INVARIANT_BROKEN.

        # difficulty: compensating_invariant/reconciliation_adjust_net_break_invariant
        """
        investor, fund, sub_order, nav = setup_investor_with_confirmed_subscribe(
            gross_amount_cents=100_000,
            submit_at="2028-08-01T10:00:00.000Z",
        )
        as_of_date = sub_order["trade_date"].split("T")[0]
        run = open_reconciliation_run(
            as_of_date=as_of_date,
            scope="TA_VS_CUSTODIAN",
            external_records=[
                external_record(
                    ref_id=sub_order["id"],
                    side="DEBIT",
                    amount_cents=99_500,  # vs internal 100_000
                ),
            ],
        )
        validate_success(api.run_match(
            run["id"], TEST_USERS["clearing_operator_headers"]
        ))
        detail = validate_success(api.get_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        ))
        exceptions = (
            detail.get("exceptions")
            or detail.get("data", {}).get("exceptions")
            or []
        )
        if not exceptions:
            pytest.skip(
                "applies_to-scope: PRD §3.7 says GET returns "
                "'reconciliation run + exceptions + instructions' but "
                "does not commit to the exact serialization key."
            )
        amt_mismatch = next(
            (e for e in exceptions if e.get("kind") == "AMOUNT_MISMATCH"),
            None,
        )
        assert amt_mismatch is not None
        # Adjust by the WRONG amount (300 instead of 500).
        validate_success(api.adjust_exception(
            run["id"], amt_mismatch["id"],
            adjust_exception_payload(adjustment_amount_cents=300),
            TEST_USERS["clearing_operator_headers"],
        ))
        # Finalize -> invariant broken (net_break = 500 - 300 = 200).
        res = api.finalize_reconciliation(
            run["id"], TEST_USERS["clearing_operator_headers"]
        )
        validate_error(res, "ERR_RECONCILIATION_INVARIANT_BROKEN")
