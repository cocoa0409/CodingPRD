"""Estimate money: per-line rounding order and the overhead-and-profit gate.

Covers the pinned round-per-line-then-sum order, the distinct-trade O&P gate at
its >= boundary, and the two-stage sequential compounding of overhead and profit.
"""
from test_helpers import (
    validate_success, ApiErrorId, setup_draft_estimate, add_line, read_estimate,
    create_estimate_line_payload, TEST_USERS,
)

ESTIMATOR = TEST_USERS["estimator_headers"]

_ZERO_TAX_3_TRADE_CARRIER = {"name": "ZeroTax Mutual", "tax_rate": 0,
                             "overhead_rate": 0.10, "profit_rate": 0.10,
                             "o_and_p_min_trades": 3}


def _entry(code, trade, price, **flags):
    spec = {"category_code": code, "trade": trade, "kind": "LABOR", "unit": "EA",
            "unit_price_cents": price}
    spec.update(flags)
    return spec


class TestPerLineRoundingThenSum:
    def test_three_third_cent_lines_sum_after_per_line_rounding(self, api):
        """PRD §3.4: "The order is load-bearing: three lines of quantity 0.335 at
        199 cents each total 201 cents when each line is rounded before summation,
        whereas summing first and rounding once would yield 200 — the
        per-line-then-sum order is the specified behavior."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            carrier_overrides={"name": "ZeroTax Mutual", "tax_rate": 0,
                               "o_and_p_min_trades": 3},
            entry_specs=(_entry("GEN-DEMO", "DEMOLITION", 199),),
            line_specs=[])
        est_id = ctx["estimate"]["id"]
        line = validate_success(api.create_estimate_line(
            est_id, create_estimate_line_payload(ctx["entries"][0]["id"], 0.335),
            ESTIMATOR), 201)
        assert line["extended_cents"] == 67, \
            "round_half_up(0.335 * 199) = round_half_up(66.665) = 67 per line"
        add_line(est_id, ctx["entries"][0]["id"], 0.335)
        add_line(est_id, ctx["entries"][0]["id"], 0.335)
        est = read_estimate(est_id)
        assert est["rcv_total_cents"] == 201, "3 * 67; sum-then-round would be 200"
        assert est["rcv_total_cents"] != 200
        assert est["overhead_profit_total_cents"] == 0, "single trade < min 3"
        assert est["tax_total_cents"] == 0

    def test_half_cent_line_rounds_half_up_before_summation(self, api):
        """PRD §3.4: "Each line's `extended_cents` is its `qty` multiplied by its
        `unit_price_cents`, rounded half up to integer cents **per line first**;
        the estimate's `rcv_total_cents` is then the sum of `extended_cents` over
        all lines whose `negotiation_status` is not `REMOVED`."
        PRD §2.8: "Whenever a multiplication produces a fractional cent, the result
        is rounded half up to the nearest integer cent, and the rounding happens at
        the stage the calculation pins — never earlier, never later."

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_beats_sum_then_round
        """
        # qty 0.5 @ 101c -> 50.5c -> 51 per line (half up);
        # two lines: 2 * 51 = 102; sum-then-round would give round(101.0) = 101.
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            entry_specs=(_entry("GEN-HALF", "GENERAL", 101),),
            line_specs=[(0, 0.5), (0, 0.5)])
        est = read_estimate(ctx["estimate"]["id"])
        assert ctx["lines"][0]["extended_cents"] == 51
        assert est["rcv_total_cents"] == 102


class TestOverheadProfitGate:
    def test_two_trades_gate_closed_three_trades_compounds(self, api):
        """PRD §3.4: "Count the distinct `trade` values over the estimate's
        non-removed lines; if that count is at least the carrier's
        `o_and_p_min_trades`, take the base as the sum of `extended_cents` over the
        non-removed lines with `o_and_p_eligible` true, compute the overhead as
        that base multiplied by the carrier's `overhead_rate` rounded half up, then
        compute the profit as the base plus overhead, multiplied by the carrier's
        `profit_rate`, again rounded half up — a sequential compounding, so profit
        is levied on the overhead-inclusive amount."
        PRD §3.4: "The estimate's `overhead_profit_total_cents` is overhead plus
        profit; when the trade gate is not met it is exactly 0."

        Design: Difficulty/combinatorial_formula/overhead_profit_three_trade_gate_and_compounding
        """
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            carrier_overrides=_ZERO_TAX_3_TRADE_CARRIER,
            entry_specs=(
                _entry("A-1", "DEMOLITION", 100, o_and_p_eligible=True),
                _entry("B-1", "DRYWALL", 100, o_and_p_eligible=True),
                _entry("C-1", "PAINT", 100, o_and_p_eligible=True),
            ),
            line_specs=[(0, 100), (1, 200)])
        est_id = ctx["estimate"]["id"]
        assert read_estimate(est_id)["overhead_profit_total_cents"] == 0, \
            "2 distinct trades < min 3 -> gate closed"
        add_line(est_id, ctx["entries"][2]["id"], 50)
        est = read_estimate(est_id)
        # base 35,000; OH round(35,000*0.10)=3,500; profit round(38,500*0.10)=3,850
        assert est["overhead_profit_total_cents"] == 7350, \
            "sequential compounding, not a flat 20% (7,000)"
        assert est["grand_total_cents"] == 42350, "35,000 base + 7,350 O&P + 0 tax"

    def test_gate_counts_all_trades_but_base_only_eligible(self, api):
        """PRD §3.4: "Count the distinct `trade` values over the estimate's
        non-removed lines; if that count is at least the carrier's
        `o_and_p_min_trades`, take the base as the sum of `extended_cents` over the
        non-removed lines with `o_and_p_eligible` true"

        Design: Difficulty/combinatorial_formula/overhead_profit_three_trade_gate_and_compounding
        """
        # 3 distinct trades open the gate, but the non-eligible line's 5,000c
        # stays out of the O&P base: base = 10,000 + 20,000 = 30,000.
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            carrier_overrides=_ZERO_TAX_3_TRADE_CARRIER,
            entry_specs=(
                _entry("A-1", "DEMOLITION", 100, o_and_p_eligible=True),
                _entry("B-1", "DRYWALL", 100, o_and_p_eligible=True),
                _entry("C-1", "PAINT", 100, o_and_p_eligible=False),
            ),
            line_specs=[(0, 100), (1, 200), (2, 50)])
        est = read_estimate(ctx["estimate"]["id"])
        # OH round(30,000*0.10)=3,000; profit round(33,000*0.10)=3,300
        assert est["overhead_profit_total_cents"] == 6300
        assert est["grand_total_cents"] == 41300, "35,000 rcv + 6,300 O&P"


class TestOverheadProfitBoundary:
    def test_o_and_p_at_exactly_three_trades(self, api):
        """PRD §3.4: "Count the distinct `trade` values over the estimate's
        non-removed lines; if that count is at least the carrier's
        `o_and_p_min_trades`"

        Design: Difficulty/boundary_precision_check/o_and_p_at_exactly_three_trades
        """
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            carrier_overrides=_ZERO_TAX_3_TRADE_CARRIER,
            entry_specs=(
                _entry("TA-1", "TA", 100, o_and_p_eligible=True),
                _entry("TB-1", "TB", 100, o_and_p_eligible=True),
                _entry("TC-1", "TC", 100, o_and_p_eligible=True),
            ),
            line_specs=[(0, 1), (1, 1)])
        est_id = ctx["estimate"]["id"]
        assert read_estimate(est_id)["overhead_profit_total_cents"] == 0, \
            "2 trades: gate closed"
        add_line(est_id, ctx["entries"][2]["id"], 1)
        est = read_estimate(est_id)
        # exactly 3 trades (>= boundary inclusive): OH round(300*0.10)=30,
        # profit round(330*0.10)=33 -> 63
        assert est["overhead_profit_total_cents"] == 63
        assert est["grand_total_cents"] == 363

    def test_o_and_p_above_boundary_stays_open(self, api):
        """PRD §3.4: "if that count is at least the carrier's `o_and_p_min_trades`,
        take the base as the sum of `extended_cents` over the non-removed lines
        with `o_and_p_eligible` true, compute the overhead as that base multiplied
        by the carrier's `overhead_rate` rounded half up, then compute the profit
        as the base plus overhead, multiplied by the carrier's `profit_rate`,
        again rounded half up"

        Design: Difficulty/boundary_precision_check/o_and_p_at_exactly_three_trades
        """
        # 4 distinct trades (threshold + 1): gate remains open; compounding holds.
        ctx = setup_draft_estimate(
            with_completed_inspection=False,
            carrier_overrides=_ZERO_TAX_3_TRADE_CARRIER,
            entry_specs=(
                _entry("TA-1", "TA", 100, o_and_p_eligible=True),
                _entry("TB-1", "TB", 100, o_and_p_eligible=True),
                _entry("TC-1", "TC", 100, o_and_p_eligible=True),
                _entry("TD-1", "TD", 100, o_and_p_eligible=True),
            ),
            line_specs=[(0, 1), (1, 1), (2, 1), (3, 1)])
        est = read_estimate(ctx["estimate"]["id"])
        # base 400; OH round(400*0.10)=40; profit round(440*0.10)=44 -> 84
        assert est["overhead_profit_total_cents"] == 84
        assert est["grand_total_cents"] == 484
