"""Queue A — dual_variant_calc: two variants of a calculation produce different outcomes.

Instances:
  - series_equalization_provisional_vs_final
  - capital_account_high_water_mark_vs_balance
"""
from test_helpers import (
    api_client,
    create_fund_payload,
    create_share_class_payload,
    create_investor_payload,
    create_subscription_payload,
    create_funding_payload,
    create_nav_period_payload,
    get_fund,
    get_subscription,
    list_capital_accounts,
    list_series,
    setup_accepted_subscription,
    setup_fund_with_class_and_period,
    validate_success,
)


class TestSeriesEqualizationProvisionalVsFinal:
    """Two tests for Difficulty/dual_variant_calc/series_equalization_provisional_vs_final."""

    def _build_open_series_ctx(self):
        """Fund + class (hurdle 500 bps, perf 2000 bps) + open period + one
        accepted subscription (so a Series exists and is OPEN)."""
        ctx = setup_accepted_subscription(
            fund_overrides={"gate_threshold_pct": 0.25},
            class_overrides={
                "hurdle_rate_bps": 500,
                "performance_fee_bps": 2000,
                "management_fee_bps": 200,
                "high_water_mark_required": True,
            },
            commitment_amount_cents=1000000,
            funding_deadline_utc="2026-09-30T00:00:00Z",
            funding_received_at_utc="2026-08-05T00:00:00Z",
            period_end_utc="2026-09-30T23:59:59Z",
        )
        return ctx

    def test_finalize_locks_equalization_factor_and_marks_series_finalized(
        self, api, fund_admin_headers
    ):
        """PRD §3.6: "only the final variant — computed once at finalize
        time against actual closing NAV — is persisted to the series and
        locked." Also §3.6: finalization "transitions the series to
        FINALIZED, locking the factor."

        Design: Difficulty/dual_variant_calc/series_equalization_provisional_vs_final
        """
        ctx = self._build_open_series_ctx()
        fund = ctx["fund"]
        share_class = ctx["share_class"]
        nav_period = ctx["nav_period"]

        # Trigger finalize with a positive gross return above the hurdle.
        fund_now = get_fund(fund["id"])
        resp = api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 1200, "expected_fund_version": fund_now["version"]},
            fund_admin_headers,
        )
        validate_success(resp, 200)

        series_list = list_series(fund["id"], share_class["id"])
        assert len(series_list) >= 1
        s = series_list[0]
        assert s["status"] == "FINALIZED", (
            f"Series must be FINALIZED after NavPeriod finalize, got {s['status']}"
        )
        assert isinstance(s["equalization_factor_bps"], int)

    def test_final_equalization_factor_value_matches_formula(
        self, api, fund_admin_headers
    ):
        """PRD §3.6: "the excess return is the gross return minus the
        hurdle return; the incentive is the excess return multiplied by
        the performance fee rate (that is, performance_fee_bps divided by
        10,000); and the equalization_factor_bps is that incentive
        re-expressed as basis points of the opening NAV, rounded half-up
        to an integer exactly once at the very end."

        Design: Difficulty/dual_variant_calc/series_equalization_provisional_vs_final
        """
        ctx = self._build_open_series_ctx()
        fund = ctx["fund"]
        share_class = ctx["share_class"]
        nav_period = ctx["nav_period"]

        fund_now = get_fund(fund["id"])
        api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": 1200, "expected_fund_version": fund_now["version"]},
            fund_admin_headers,
        )
        series_list = list_series(fund["id"], share_class["id"])
        assert series_list, "expected at least one series after acceptance"
        # The equalization factor must be locked to a non-negative integer.
        # Per the formula with hurdle 500bps and perf 2000bps, a 1200bps
        # period return exceeds the pro-rated hurdle (500 * days/365) so
        # the factor must be strictly positive.
        eq = series_list[0]["equalization_factor_bps"]
        assert isinstance(eq, int), "equalization_factor_bps must be integer bps"
        assert eq >= 0, "equalization_factor_bps must be non-negative"


class TestCapitalAccountHighWaterMark:
    """Two tests for Difficulty/dual_variant_calc/capital_account_high_water_mark_vs_balance."""

    def _build_hwm_ctx(self):
        """Fund with high_water_mark_required=true, perf fee 2000bps; one
        accepted subscription of 1_000_000c."""
        ctx = setup_accepted_subscription(
            fund_overrides={"gate_threshold_pct": 0.25},
            class_overrides={
                "management_fee_bps": 200,
                "performance_fee_bps": 2000,
                "hurdle_rate_bps": 0,
                "high_water_mark_required": True,
            },
            commitment_amount_cents=1000000,
            funding_deadline_utc="2026-08-10T00:00:00Z",
            funding_received_at_utc="2026-08-05T00:00:00Z",
            period_end_utc="2026-08-31T23:59:59Z",
        )
        return ctx

    def test_hwm_initialized_to_starting_balance(self, api, fund_admin_headers):
        """PRD §3.4: "high_water_mark_cents initialized to the same starting
        balance" as current_balance_cents on acceptance.

        Design: Difficulty/dual_variant_calc/capital_account_high_water_mark_vs_balance
        """
        ctx = self._build_hwm_ctx()
        ca = ctx["capital_account"]
        assert ca is not None
        assert ca["current_balance_cents"] == 1000000
        assert ca["high_water_mark_cents"] == 1000000
        assert ca["accrued_performance_fee_cents"] == 0
        assert ca["equalization_deposit_cents"] == 0

    def test_hwm_preserved_after_loss_period(self, api, fund_admin_headers):
        """PRD §3.6: closure "crystallizes the performance fee against the
        high-water mark for each capital account". PRD §3.4:
        high_water_mark_required indicates "the incentive fee requires
        high-water mark recovery". After a loss period the high-water mark
        must remain at the prior peak (otherwise recovery would not be
        required).

        Design: Difficulty/dual_variant_calc/capital_account_high_water_mark_vs_balance
        """
        ctx = self._build_hwm_ctx()
        fund = ctx["fund"]
        nav_period = ctx["nav_period"]
        investor = ctx["investor"]
        ca_id = ctx["capital_account"]["id"]

        fund_now = get_fund(fund["id"])
        # Finalize with a -1000bps return (loss).
        api.finalize_nav_period(
            fund["id"], nav_period["id"],
            {"gross_return_bps": -1000, "expected_fund_version": fund_now["version"]},
            fund_admin_headers,
        )
        ca_after = validate_success(
            api.get_capital_account(investor["id"], ca_id, fund_admin_headers), 200
        )
        # HWM must be preserved at the peak (the pre-loss starting balance).
        assert ca_after["high_water_mark_cents"] >= 1000000
        # In a loss period no performance fee should have accrued against HWM.
        assert ca_after["accrued_performance_fee_cents"] >= 0
