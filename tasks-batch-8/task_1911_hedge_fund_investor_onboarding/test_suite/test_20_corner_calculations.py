"""Queue B — calculations: equalization factor edge, notice-days with LIQUIDITY clause.

Instances:
  - equalization_factor_zero_when_return_below_hurdle
  - notice_days_liquidity_clause_reduction
"""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_mfn_clause,
    create_redemption_payload,
    get_fund,
    list_series,
    setup_accepted_subscription,
    setup_executed_side_letter,
    make_investor_headers,
    validate_success,
)

FA = TEST_USERS["fund_admin_headers"]
TA = TEST_USERS["transfer_agent_headers"]


class TestEqualizationFactorBelowHurdle:
    def test_equalization_factor_zero_when_return_below_hurdle(self, api, fund_admin_headers):
        """PRD §3.6: "If the gross return is at or below the hurdle return
        — including any period where the closing NAV is below the opening
        NAV — the equalization factor is 0."

        Design: Corner/calculations/equalization_factor_zero_when_return_below_hurdle
        """
        ctx = setup_accepted_subscription(
            class_overrides={
                "hurdle_rate_bps": 800,
                "performance_fee_bps": 2000,
                "high_water_mark_required": False,
            },
            commitment_amount_cents=200000,
        )
        fund = ctx["fund"]
        share_class = ctx["share_class"]
        nav_period = ctx["nav_period"]

        fv = get_fund(fund["id"])["version"]
        # PRD §3.6 pro-rates the hurdle: hurdle return = (800/10000) *
        # (days_in_period/365). For this ~30-day period that is ~66 bps, so a
        # 50 bps gross return is at-or-below the hurdle and the equalization
        # factor must be 0.
        api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 50, "expected_fund_version": fv},
            fund_admin_headers,
        )
        series = list_series(fund["id"], share_class["id"])
        assert series, "expected at least one series"
        for s in series:
            assert s["equalization_factor_bps"] == 0, (
                f"Expected equalization_factor_bps=0 below hurdle, got {s['equalization_factor_bps']}"
            )


class TestNoticeDaysLiquidityClauseReduction:
    def test_notice_days_liquidity_clause_reduction(self, api, fund_admin_headers):
        """PRD §3.7: "The required notice is the share class's notice_days
        minus the sum of notice_days_reduction across the investor's
        applicable elected LIQUIDITY clauses, floored at 0." Also: "The
        boundary operator is inclusive: an actual notice exactly equal to
        the required notice is valid."

        Design: Corner/calculations/notice_days_liquidity_clause_reduction
        """
        # Base notice_days=30; elected LIQUIDITY clause reduces by 5 → required=25.
        ctx = setup_accepted_subscription(
            fund_overrides={"notice_days_default": 30, "gate_threshold_pct": 0.50},
            class_overrides={
                "lockup_months": 0, "notice_days": 30,
                "redemption_frequency": "QUARTERLY",
            },
            commitment_amount_cents=500000,
            funding_deadline_utc="2026-08-05T00:00:00Z",
            funding_received_at_utc="2026-08-04T00:00:00Z",
            period_end_utc="2026-09-30T00:00:00Z",
        )
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        investor = ctx["investor"]
        capital_account = ctx["capital_account"]

        clause = create_mfn_clause(
            fund["id"],
            clause_tag="LIQUIDITY", clause_text="shave 5",
            capacity_threshold_cents=0, fee_rebate_bps=0, notice_days_reduction=5,
        )
        ctx = setup_executed_side_letter(ctx)
        investor_headers = make_investor_headers(investor["id"])
        api.elect_mfn(
            fund["id"], ctx["side_letter"]["id"],
            {"mfn_clause_id": clause["id"]},
            investor_headers,
        )

        # Advance clock so actual notice = 25 days (= 30 base - 5 reduction).
        api.set_current_utc({"to_iso8601": "2026-09-05T00:00:00Z"}, fund_admin_headers)
        red = validate_success(
            api.create_redemption(
                fund["id"],
                create_redemption_payload(
                    capital_account_id=capital_account["id"],
                    requested_amount_cents=100000,
                    requested_effective_period_id=nav_period["id"],
                ),
                TA,
            ),
            201,
        )
        resp = api.approve_redemption(fund["id"], red["id"], fund_admin_headers)
        approved = validate_success(resp, 200)
        assert approved["status"] == "APPROVED"
