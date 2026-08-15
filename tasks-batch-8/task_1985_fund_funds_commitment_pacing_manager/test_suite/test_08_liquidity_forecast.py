"""Liquidity forecast: base variant vs stress variant (PRD §3.6)."""
import pytest

from test_helpers import (
    api_client,
    create_pending_distribution,
    setup_with_executed_commitment,
    validate_success,
)


class TestLiquidityForecastVariants:
    def test_liquidity_forecast_base_vs_stress_variant(self):
        """PRD §3.6: "A forward liquidity projection is exposed for the
        program, covering the next 8 quarters from the server's logical-clock
        quarter."
        PRD §3.6: "Each `PENDING` distribution contributes its `amount` as an
        inflow in the quarter containing its `received_at`."
        PRD §3.6: "The forecast's `forecast_net_cash` for each quarter is the
        current `unrestricted_cash` minus the quarter's expected calls, minus
        the quarter's issued-or-overdue calls, minus the accepted purchase
        prices, plus the quarter's pending distribution inflows; all amounts
        are rounded to 2 decimal places round half up."
        PRD §3.6: "When the requester passes the `stress` query flag, a stress
        variant is applied: pending distributions are excluded from inflows
        and expected calls are scaled by a factor of 1.15, with the same
        inclusion set otherwise."

        Design: Difficulty/dual_variant_calc/liquidity_forecast_base_vs_stress_variant
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="2d",
            program_name="P2",
        )
        create_pending_distribution(
            ctx, amount=500_000, distribution_type="INCOME",
            received_at="2026-09-15T00:00:00Z",
        )
        base = validate_success(
            api_client.get_liquidity_forecast(ctx.program["id"], ctx.analyst_headers)
        )
        stress = validate_success(
            api_client.get_liquidity_forecast(
                ctx.program["id"], ctx.analyst_headers, params={"stress": "true"}
            )
        )
        base_fc = base["forecast_net_cash"]
        stress_fc = stress["forecast_net_cash"]
        assert len(base_fc) == 8, "base variant returns exactly 8 quarterly entries"
        assert len(stress_fc) == 8, "stress variant returns exactly 8 quarterly entries"
        # Current quarter (2026-Q3 per the default 2026-08-01 clock):
        # base counts the +500,000 pending distribution; stress excludes it and
        # scales expected calls by 1.15 -> stress strictly lower in quarter 0.
        assert stress_fc[0] < base_fc[0], (
            f"stress quarter-0 ({stress_fc[0]}) must be below base ({base_fc[0]})"
        )

    def test_liquidity_forecast_stress_scales_expected_calls(self):
        """PRD §3.6: "When the requester passes the `stress` query flag, a
        stress variant is applied: pending distributions are excluded from
        inflows and expected calls are scaled by a factor of 1.15, with the
        same inclusion set otherwise. The response carries the `program_id`,
        the `base_quarter`, the `forecast_net_cash` array, and the program's
        current `posture`."

        Second test on the same instance: with no PENDING distributions and
        unfunded commitments outstanding, stress is below base in at least one
        quarter and the response envelope carries the declared fields.

        Design: Difficulty/dual_variant_calc/liquidity_forecast_base_vs_stress_variant
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=10_000_000, staff_prefix="2e",
            program_name="P2B",
        )
        base = validate_success(
            api_client.get_liquidity_forecast(ctx.program["id"], ctx.analyst_headers)
        )
        stress = validate_success(
            api_client.get_liquidity_forecast(
                ctx.program["id"], ctx.analyst_headers, params={"stress": "true"}
            )
        )
        assert base["program_id"] == ctx.program["id"]
        assert isinstance(base["base_quarter"], str) and base["base_quarter"]
        assert base["posture"] in ("NORMAL", "RESTRICTED", "FROZEN")
        assert len(base["forecast_net_cash"]) == 8
        assert len(stress["forecast_net_cash"]) == 8
        # The commitment's unfunded 10,000,000 feeds expected calls; stress
        # scales them by 1.15, so at least one quarter is strictly lower and
        # no quarter is higher.
        diffs = [b - s for b, s in zip(base["forecast_net_cash"], stress["forecast_net_cash"])]
        assert any(d > 0.005 for d in diffs), (
            "stress must be strictly lower somewhere when expected calls exist"
        )
        assert all(d >= -0.005 for d in diffs), "stress never exceeds base"
