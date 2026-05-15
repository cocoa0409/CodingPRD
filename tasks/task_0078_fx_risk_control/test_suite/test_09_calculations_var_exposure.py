"""Risk calculations — VaR (round-per-position-then-sum) and gross/net exposure.

Citations refer to PRD.md §3.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    Z_99,
    book_trade,
    create_currency_pair,
    create_trader,
    make_trader_headers,
    round_half_up,
    setup_trader_with_limits,
    validate_success,
)
from test_helpers.fixtures import create_counterparty, create_limit, set_clock


# ===========================================================================
# VaR — PRD §3.8
# ===========================================================================
class TestValueAtRisk:
    """PRD §3.8: VaR computation order is fixed — round per position, then
    sum. PRD §3.8 names the z-score 2.326 explicitly.

    # difficulty: combinatorial_formula/var_round_per_position_then_sum
    """

    def test_single_position_var_uses_z99_2_326(self, api):
        """PRD §3.8: "first, for each of the trader's positions with
        non-zero `net_base`, compute the position's USD exposure as the
        absolute value of `net_open_usd`; second, compute the per-pair VaR
        as the exposure multiplied by the pair's `daily_volatility`
        multiplied by 2.326; third, round each per-pair VaR half-up to two
        decimal places; fourth, sum the rounded per-pair VaRs to produce
        the trader's total VaR."

        Claim: a single 1M USD EURUSD position with daily_volatility=0.008
        yields var_99_1d_usd == round_half_up(1000000 * 0.008 * 2.326, 2).
        """
        ctx = setup_trader_with_limits(
            intraday_cap=100_000_000.00,
            overnight_cap=100_000_000.00,
            pair_mid_rate=1.000000,
            pair_volatility=0.008000,
        )
        book_trade(
            trader_id=ctx["trader"]["id"],
            pair_code=ctx["pair"]["code"],
            side="BUY",
            notional_base=1_000_000.00,
            entry_rate=1.000000,
            counterparty_id=ctx["counterparty"]["id"],
        )
        res = api.get_var(ctx["trader"]["id"], ctx["trader_headers"])
        data = validate_success(res, 200)
        expected = round_half_up(1_000_000.00 * 0.008 * Z_99, 2)
        assert data["var_99_1d_usd"] == expected, (
            f"PRD §3.8: VaR = round_half_up(exposure * vol * 2.326, 2) = "
            f"{expected}; got {data['var_99_1d_usd']!r}"
        )

    def test_two_positions_round_per_position_then_sum(self, api):
        """PRD §3.8: "third, round each per-pair VaR half-up to two
        decimal places; fourth, sum the rounded per-pair VaRs to produce
        the trader's total VaR. This is 'round per position, then sum'."

        Setup: two 1M USD positions on different pairs, each with its own
        daily_volatility. Expected VaR follows PRD §3.8's step ordering:
        round each per-pair VaR to 2dp, then sum.

        Claim: var_99_1d_usd == round(per_pair_eur, 2) + round(per_pair_gbp, 2).

        # difficulty: combinatorial_formula/var_round_per_position_then_sum
        """
        set_clock("2026-05-13T10:00:00.000Z")
        eurusd = create_currency_pair(
            code="EURUSD", base_ccy="EUR", quote_ccy="USD",
            mid_rate=1.000000, daily_volatility=0.001595,
        )
        gbpusd = create_currency_pair(
            code="GBPUSD", base_ccy="GBP", quote_ccy="USD",
            mid_rate=1.000000, daily_volatility=0.001597,
        )
        trader = create_trader()
        cp = create_counterparty(external_rating="AAA", internal_score=90)
        create_limit(
            trader["id"], bucket="INTRADAY",
            notional_cap_usd=10_000_000.00,
        )
        create_limit(
            trader["id"], bucket="OVERNIGHT",
            notional_cap_usd=100_000_000.00,
        )
        # Position 1
        api_book = book_trade
        api_book(
            trader_id=trader["id"], pair_code=eurusd["code"], side="BUY",
            notional_base=1_000_000.00, entry_rate=1.000000,
            counterparty_id=cp["id"],
        )
        api_book(
            trader_id=trader["id"], pair_code=gbpusd["code"], side="BUY",
            notional_base=1_000_000.00, entry_rate=1.000000,
            counterparty_id=cp["id"],
        )
        res = api.get_var(trader["id"], make_trader_headers(trader["id"]))
        data = validate_success(res, 200)
        var_a = round_half_up(1_000_000.00 * 0.001595 * Z_99, 2)
        var_b = round_half_up(1_000_000.00 * 0.001597 * Z_99, 2)
        expected = round_half_up(var_a + var_b, 2)
        assert data["var_99_1d_usd"] == expected, (
            f"PRD §3.8 'round per position, then sum': "
            f"per-pair {var_a} + {var_b} = {expected}; "
            f"got {data['var_99_1d_usd']!r}."
        )

    def test_zero_position_contributes_nothing(self, api):
        """PRD §3.8: "for each of the trader's positions with non-zero
        `net_base`".

        Claim: a trader with no booked trades reports var_99_1d_usd == 0.
        """
        ctx = setup_trader_with_limits()
        res = api.get_var(ctx["trader"]["id"], ctx["trader_headers"])
        data = validate_success(res, 200)
        assert data["var_99_1d_usd"] == 0


# ===========================================================================
# Exposure — PRD §3.8
# ===========================================================================
def test_gross_exposure_sums_absolute_net_open_usd(api):
    """PRD §3.8: "A trader's gross exposure is the sum of the absolute USD
    value of every open position across pairs, with no netting between
    pairs. Concretely, the system iterates the trader's `Position` rows,
    takes the absolute value of each row's `net_open_usd`, accumulates
    the running total, and rounds the final sum half-up to two decimal
    places."

    Claim: with a +1.1M USD EURUSD position and a -1.25M USD GBPUSD
    position (book one BUY EURUSD + one SELL GBPUSD), gross_usd ==
    abs(1100000) + abs(-1250000) == 2350000.00.

    # difficulty: combinatorial_formula/net_vs_gross_combinatorial_aggregation
    """
    set_clock("2026-05-13T10:00:00.000Z")
    eurusd = create_currency_pair(
        code="EURUSD", base_ccy="EUR", quote_ccy="USD",
        mid_rate=1.100000, daily_volatility=0.005000,
    )
    gbpusd = create_currency_pair(
        code="GBPUSD", base_ccy="GBP", quote_ccy="USD",
        mid_rate=1.250000, daily_volatility=0.005000,
    )
    trader = create_trader()
    cp = create_counterparty(external_rating="AAA", internal_score=90)
    create_limit(trader["id"], bucket="INTRADAY", notional_cap_usd=100_000_000.00)
    create_limit(trader["id"], bucket="OVERNIGHT", notional_cap_usd=100_000_000.00)
    book_trade(
        trader_id=trader["id"], pair_code=eurusd["code"], side="BUY",
        notional_base=1_000_000.00, entry_rate=1.100000,
        counterparty_id=cp["id"],
    )
    book_trade(
        trader_id=trader["id"], pair_code=gbpusd["code"], side="SELL",
        notional_base=1_000_000.00, entry_rate=1.250000,
        counterparty_id=cp["id"],
    )
    res = api.get_exposure(trader["id"], make_trader_headers(trader["id"]))
    data = validate_success(res, 200)
    assert data["gross_usd"] == 2_350_000.00, (
        f"PRD §3.8: gross_usd = |1.1M| + |-1.25M| = 2_350_000.00; "
        f"got {data['gross_usd']!r}"
    )


def test_net_exposure_netting_reduces_versus_gross(api):
    """PRD §3.8: "Net exposure decomposes each pair's position into two
    single-currency legs in USD terms — a leg in the pair's `base_ccy` and
    a leg in its `quote_ccy` — and then nets across pairs that share a
    currency. ... A trader who is long `EURUSD` and short `GBPUSD` will
    see the USD legs partially offset under this rule".

    Claim: for the same setup as gross-exposure (BUY 1M EURUSD @ 1.10 +
    SELL 1M GBPUSD @ 1.25), net_usd < gross_usd.
    """
    set_clock("2026-05-13T10:00:00.000Z")
    eurusd = create_currency_pair(
        code="EURUSD", base_ccy="EUR", quote_ccy="USD",
        mid_rate=1.100000, daily_volatility=0.005000,
    )
    gbpusd = create_currency_pair(
        code="GBPUSD", base_ccy="GBP", quote_ccy="USD",
        mid_rate=1.250000, daily_volatility=0.005000,
    )
    trader = create_trader()
    cp = create_counterparty(external_rating="AAA", internal_score=90)
    create_limit(trader["id"], bucket="INTRADAY", notional_cap_usd=100_000_000.00)
    create_limit(trader["id"], bucket="OVERNIGHT", notional_cap_usd=100_000_000.00)
    book_trade(
        trader_id=trader["id"], pair_code=eurusd["code"], side="BUY",
        notional_base=1_000_000.00, entry_rate=1.100000,
        counterparty_id=cp["id"],
    )
    book_trade(
        trader_id=trader["id"], pair_code=gbpusd["code"], side="SELL",
        notional_base=1_000_000.00, entry_rate=1.250000,
        counterparty_id=cp["id"],
    )
    res = api.get_exposure(trader["id"], make_trader_headers(trader["id"]))
    data = validate_success(res, 200)
    assert data["gross_usd"] == 2_350_000.00
    assert data["net_usd"] < data["gross_usd"], (
        f"PRD §3.8: long EURUSD + short GBPUSD share USD axis and partially "
        f"offset; net_usd ({data['net_usd']}) must be strictly less than "
        f"gross_usd ({data['gross_usd']})"
    )
