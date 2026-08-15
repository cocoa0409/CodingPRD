"""Margin accounting: execution gates, call thresholds, funding cures, offset,
and pinned-order forced liquidation."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    setup_operation_with_active_plan,
    setup_margin_account,
    setup_account_in_margin_call,
    create_accepted_recommendation,
    create_open_position,
    create_recommendation_payload,
    record_settlement_tick,
)

ADVISOR = TEST_USERS["advisor_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _margin_ctx(name, funding, acres=1000, max_priced_pct=0.80, risk_profile="BALANCED"):
    ctx = setup_operation_with_active_plan(
        name=name, risk_profile=risk_profile, planted_acres=acres, max_priced_pct=max_priced_pct
    )
    setup_margin_account(ctx, initial_funding=funding)
    return ctx


class TestExecutionGates:
    def test_execute_proposed_rec_state_error_beats_margin_fiscal(self, api):
        """PRD §2.6: "Sixth, the target resource must be in a from-state that
        permits the requested transition, producing `ERR_INVALID_STATE`." and
        "Eleventh and last, the post-trade solvency checks run, producing
        `ERR_INSUFFICIENT_MARGIN_EQUITY`. A request failing an earlier check
        never reaches a later one, so the returned error always identifies the
        highest-priority violation present."
        PRD §3.5: "Execution turns an `ACCEPTED` recommendation into a live
        position and is performed by a `CommodityAdvisor`."

        Design: Difficulty/priority_pair_validation_conflict/execute_proposed_rec_state_error_beats_margin_fiscal
        """
        ctx = _margin_ctx("Prio Farm 1", funding=100)
        record_settlement_tick(4.50, "2026-06-01")
        rec = get_success_data(api.create_recommendation(
            create_recommendation_payload(ctx["plan"]["id"], bushels=50000), ADVISOR))
        assert rec["status"] == "PROPOSED"
        resp = api.execute_recommendation(rec["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_recommendation(rec["id"], ADVISOR))
        assert after["status"] == "PROPOSED", "the state-rejected execute must not move the recommendation"

    def test_execute_proposed_rec_leaves_no_position(self, api):
        """PRD §3.5: "Execution turns an `ACCEPTED` recommendation into a live
        position and is performed by a `CommodityAdvisor`." and "On success the
        server mints a `BrokeragePosition` in `OPEN` status."
        PRD §2.6: "A request failing an earlier check never reaches a later
        one, so the returned error always identifies the highest-priority
        violation present."

        Design: Difficulty/priority_pair_validation_conflict/execute_proposed_rec_state_error_beats_margin_fiscal
        """
        ctx = _margin_ctx("Prio Farm 1", funding=100)
        record_settlement_tick(4.50, "2026-06-01")
        rec = get_success_data(api.create_recommendation(
            create_recommendation_payload(ctx["plan"]["id"], bushels=50000), ADVISOR))
        resp = api.execute_recommendation(rec["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        from test_helpers import validate_paginated
        positions, _meta = validate_paginated(
            api.list_positions(ADVISOR, params={"operation_id": ctx["operation"]["id"]})
        )
        assert positions == [], "no BrokeragePosition may be minted by the rejected execution"

    def test_execute_without_settlement_tick_returns_409(self, api):
        """PRD §3.5: "Second, a `SETTLEMENT` tick must exist for the
        operation's `primary_commodity` and the recommendation's
        `contract_month` — otherwise `ERR_NO_SETTLEMENT_PRICE`."

        Design: Corner/endpoints/execute_without_settlement_tick_returns_409
        """
        ctx = _margin_ctx("NoTick Farm", funding=50000)
        rec = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], bushels=10000)
        resp = api.execute_recommendation(rec["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_NO_SETTLEMENT_PRICE)
        after = get_success_data(api.get_recommendation(rec["id"], ADVISOR))
        assert after["status"] == "ACCEPTED", "the recommendation must stay ACCEPTED after the rejection"

    def test_execute_with_insufficient_equity_rejected(self, api):
        """PRD §3.5: "Third, the post-trade solvency check: after the position
        opens, the account's `cash_balance` must be at least the total
        `initial_margin_required` and the `margin_equity` must be at least the
        total `maintenance_margin_required`, otherwise the execution is
        rejected with `ERR_INSUFFICIENT_MARGIN_EQUITY`."

        Design: Corner/endpoints/execute_with_insufficient_equity_rejected
        """
        ctx = _margin_ctx("Solv Farm", funding=5000)
        record_settlement_tick(4.50, "2026-06-01")
        rec = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], bushels=50000)
        resp = api.execute_recommendation(rec["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MARGIN_EQUITY)
        account = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert account["cash_balance"] == pytest.approx(5000.00), "the rejected execution must not touch cash"
        assert account["initial_margin_required"] == pytest.approx(0.00), "no position may be opened"

    def test_execute_in_restricted_account_returns_409(self, api):
        """PRD §3.6: "After the run, if positions remain and equity is at or
        above maintenance, the account returns to `FUNDED`; if no positions
        remain and equity is non-negative, the account is `FUNDED`; if no
        positions remain and equity is negative, the account moves to
        `RESTRICTED`."
        PRD §3.5: "First, the operation's margin account must exist and be in
        `FUNDED` status: a `CALL_OUTSTANDING` account rejects with
        `ERR_MARGIN_CALL_OUTSTANDING`, and a `RESTRICTED` account rejects with
        `ERR_MARGIN_ACCOUNT_RESTRICTED`."

        Design: Corner/endpoints/execute_in_restricted_account_returns_409
        """
        ctx = _margin_ctx("Restr Farm", funding=16000)
        record_settlement_tick(4.50, "2026-06-01")
        pos_a = create_open_position(ctx, bushels=30000)
        pos_b = create_open_position(ctx, bushels=20000)
        record_settlement_tick(4.90, "2026-07-01")
        get_success_data(api.liquidate_margin_account(ctx["account"]["id"], ADMIN))
        account = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert account["status"] == "RESTRICTED", (
            "liquidation exhausting all positions at negative equity leaves the account RESTRICTED"
        )
        assert account["cash_balance"] == pytest.approx(-4000.00), (
            f"A realized -12000.00 then B -8000.00 against 16000.00 funding; got {account['cash_balance']}"
        )
        rec_c = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], bushels=1000)
        resp = api.execute_recommendation(rec_c["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_MARGIN_ACCOUNT_RESTRICTED)


class TestMarginCallAndCure:
    def test_recommendation_execute_blocked_by_margin_call(self, api):
        """PRD §3.5: "First, the operation's margin account must exist and be
        in `FUNDED` status: a `CALL_OUTSTANDING` account rejects with
        `ERR_MARGIN_CALL_OUTSTANDING`, and a `RESTRICTED` account rejects with
        `ERR_MARGIN_ACCOUNT_RESTRICTED`."
        PRD §3.4: "When an account's `margin_equity` falls strictly below its
        `maintenance_margin_required`, the account moves from `FUNDED` to
        `CALL_OUTSTANDING` with `margin_call_amount` frozen at
        `initial_margin_required` minus `margin_equity` at issuance."

        Design: Difficulty/cross_entity_state_dependency/recommendation_execute_blocked_by_margin_call
        """
        ctx = setup_account_in_margin_call(initial_funding=15000)
        account = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert account["status"] == "CALL_OUTSTANDING", (
            "tick 4.70 on a 50000-bu short entered at 4.50 with 15000 cash drives equity to 5000.00"
        )
        assert account["margin_call_amount"] == pytest.approx(10000.00, abs=0.005), (
            "call frozen at issuance as initial 15000.00 minus equity 5000.00"
        )
        rec2 = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], bushels=1000)
        resp = api.execute_recommendation(rec2["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_MARGIN_CALL_OUTSTANDING)

    def test_funding_exactly_to_initial_cures_and_unblocks_execute(self, api):
        """PRD §3.6: "A funding deposit cures the call when the post-funding
        `margin_equity` is at least `initial_margin_required` — equality cures
        — returning the account to `FUNDED` and clearing `margin_call_amount`
        to zero; a deposit that does not reach that threshold leaves the
        account `CALL_OUTSTANDING` with a reduced `margin_call_amount`."
        PRD §3.5: "its `entry_price` is the latest `SETTLEMENT` tick price for
        the commodity and contract month selected per §2.11."

        Design: Difficulty/cross_entity_state_dependency/recommendation_execute_blocked_by_margin_call
        """
        ctx = setup_account_in_margin_call(initial_funding=15000)
        account_id = ctx["account"]["id"]
        rec2 = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], bushels=1000)
        blocked = api.execute_recommendation(rec2["id"], ADVISOR)
        validate_error(blocked, ApiErrorId.ERR_MARGIN_CALL_OUTSTANDING)
        funded = get_success_data(api.fund_margin_account(
            account_id, {"amount": 10000}, make_grower_headers(ctx["operation"]["id"])))
        assert funded["status"] == "FUNDED", (
            "post-fund equity 15000.00 >= initial 15000.00 — equality cures"
        )
        assert funded["margin_call_amount"] == pytest.approx(0.00), "cure clears the call amount to zero"
        executed = get_success_data(api.execute_recommendation(rec2["id"], ADVISOR))
        assert executed["status"] == "OPEN"
        assert executed["entry_price"] == pytest.approx(4.70), (
            "entry must be the latest SETTLEMENT tick price (4.70)"
        )

    def test_margin_call_strict_threshold_boundary(self, api):
        """PRD §3.4: "When an account's `margin_equity` falls strictly below
        its `maintenance_margin_required`, the account moves from `FUNDED` to
        `CALL_OUTSTANDING` with `margin_call_amount` frozen at
        `initial_margin_required` minus `margin_equity` at issuance."
        PRD §2.10: "When the account enters `CALL_OUTSTANDING`, the
        `margin_call_amount` is frozen at issuance as `initial_margin_required`
        minus `margin_equity`; at all other times it is zero."

        Design: Corner/cross_cutting_complexity_layers/margin_call_strict_threshold_boundary
        """
        ctx = _margin_ctx("Thresh Farm", funding=20000)
        record_settlement_tick(4.50, "2026-06-01")
        create_open_position(ctx, bushels=50000)
        record_settlement_tick(4.68, "2026-07-01")
        at_equal = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert at_equal["margin_equity"] == pytest.approx(11000.00, abs=0.005)
        assert at_equal["status"] == "FUNDED", (
            "equity exactly equal to maintenance (11000.00) must NOT trigger a call — strict <"
        )
        assert at_equal["margin_call_amount"] == pytest.approx(0.00)
        record_settlement_tick(4.69, "2026-07-02")
        below = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert below["margin_equity"] == pytest.approx(10500.00, abs=0.005)
        assert below["status"] == "CALL_OUTSTANDING", "10500.00 < 11000.00 must issue the call"
        assert below["margin_call_amount"] == pytest.approx(4500.00, abs=0.005), (
            "call frozen at initial 15000.00 minus equity 10500.00"
        )


class TestOffsetAndLiquidation:
    def test_offset_relieves_margin_call(self, api):
        """PRD §3.6: "The position moves from `OPEN` to `OFFSET`, `exit_price`
        is set to the latest settlement tick, `realized_pnl` is computed by the
        same two instrument formulas as liquidation, the realized amount is
        added to `cash_balance`, margin aggregates are recomputed, the call
        status is re-evaluated — equity at or above the initial requirement
        returns the account to `FUNDED` — and the plan's `hedged_bushels` is
        recomputed."

        Design: Corner/state_machines/offset_relieves_margin_call
        """
        ctx = setup_account_in_margin_call(initial_funding=20000)
        pre = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert pre["status"] == "CALL_OUTSTANDING"
        assert pre["margin_call_amount"] == pytest.approx(5000.00, abs=0.005)
        offset = get_success_data(api.offset_position(ctx["position"]["id"], ADVISOR))
        assert offset["status"] == "OFFSET"
        assert offset["realized_pnl"] == pytest.approx(-10000.00, abs=0.005), (
            "(entry 4.50 - exit 4.70) * 50000 == -10000.00"
        )
        post = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert post["cash_balance"] == pytest.approx(10000.00, abs=0.005)
        assert post["status"] == "FUNDED", "no open positions -> requirements 0 -> account returns to FUNDED"

    def test_liquidate_funded_account_rejected(self, api):
        """PRD §3.6: "When the account is `CALL_OUTSTANDING` and the grower
        cannot cure, a `PlatformAdmin` may invoke forced liquidation; calling
        it while the account is not `CALL_OUTSTANDING` is rejected with
        `ERR_LIQUIDATION_NOT_REQUIRED`."

        Design: Corner/endpoints/liquidate_funded_account_rejected
        """
        from test_helpers import create_operation, create_margin_account_payload
        op = create_operation(name="NoLiq Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED")
        account = get_success_data(api.create_margin_account(
            create_margin_account_payload(op["id"], initial_funding=10000), ADVISOR))
        resp = api.liquidate_margin_account(account["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_LIQUIDATION_NOT_REQUIRED)
        after = get_success_data(api.get_margin_account(account["id"], ADVISOR))
        assert after["status"] == "FUNDED"
        assert after["cash_balance"] == pytest.approx(10000.00)

    def test_liquidation_largest_margin_first_spares_smaller(self, api):
        """PRD §3.6: "Third, the candidate set is ordered by
        `initial_margin_dollars` descending, with ties broken by `created_at`
        ascending. Fourth, while the deficit test holds and candidates remain,
        the head candidate is liquidated: it moves from `OPEN` to `LIQUIDATED`,
        its `exit_price` is the frozen settlement mark, its `realized_pnl` is
        computed — for `FUTURES_SHORT`, the entry price minus the exit price
        multiplied by `bushels`; for `LONG_PUT`, the greater of zero and the
        strike minus the exit, minus `premium_per_bushel`, multiplied by
        `bushels` — the realized amount is applied to `cash_balance`, the
        position leaves the candidate set, and the aggregates are recomputed.
        Fifth, the loop stops as soon as the deficit test fails."

        Design: Difficulty/combinatorial_formula/forced_liquidation_pinned_evaluation_order
        """
        ctx = _margin_ctx("Liq Farm", funding=20000)
        record_settlement_tick(4.50, "2026-06-01")
        pos_a = create_open_position(ctx, bushels=30000)  # IM 9000 — the larger contributor
        pos_b = create_open_position(ctx, bushels=20000)  # IM 6000
        record_settlement_tick(4.70, "2026-07-01")
        pre = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert pre["margin_equity"] == pytest.approx(10000.00, abs=0.005)
        assert pre["status"] == "CALL_OUTSTANDING"
        assert pre["margin_call_amount"] == pytest.approx(5000.00, abs=0.005)
        get_success_data(api.liquidate_margin_account(ctx["account"]["id"], ADMIN))
        a = get_success_data(api.get_position(pos_a["id"], ADVISOR))
        b = get_success_data(api.get_position(pos_b["id"], ADVISOR))
        assert a["status"] == "LIQUIDATED", "largest-margin contributor liquidates first"
        assert a["realized_pnl"] == pytest.approx(-6000.00, abs=0.005)
        assert b["status"] == "OPEN", (
            "the deficit test fails after A closes (equity 10000.00 >= B's maintenance 4400.00) — B is spared"
        )

    def test_liquidation_restores_funded_with_survivor(self, api):
        """PRD §3.6: "After the run, if positions remain and equity is at or
        above maintenance, the account returns to `FUNDED`; if no positions
        remain and equity is non-negative, the account is `FUNDED`; if no
        positions remain and equity is negative, the account moves to
        `RESTRICTED`." and "The pinned order is observable: liquidating the
        largest margin contributor first can spare smaller positions that a
        smallest-first order would have closed."

        Design: Difficulty/combinatorial_formula/forced_liquidation_pinned_evaluation_order
        """
        ctx = _margin_ctx("Liq Farm", funding=20000)
        record_settlement_tick(4.50, "2026-06-01")
        create_open_position(ctx, bushels=30000)
        pos_b = create_open_position(ctx, bushels=20000)
        record_settlement_tick(4.70, "2026-07-01")
        get_success_data(api.liquidate_margin_account(ctx["account"]["id"], ADMIN))
        account = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert account["status"] == "FUNDED", "positions remain and equity 10000.00 >= maintenance 4400.00"
        assert account["cash_balance"] == pytest.approx(14000.00, abs=0.005), (
            "20000.00 funding minus A's realized 6000.00"
        )
        b = get_success_data(api.get_position(pos_b["id"], ADVISOR))
        assert b["status"] == "OPEN"


class TestOpenOffsetConservation:
    def test_position_open_offset_conserve_margin_cash(self, api):
        """PRD §2.10: "The account's `cash_balance` is the cumulative funding
        deposited, plus realized profit-and-loss from closed positions, minus
        option premiums debited at execution. `initial_margin_required` is the
        sum of `initial_margin_dollars` over the account's `OPEN` positions,
        and `maintenance_margin_required` is the sum of
        `maintenance_margin_dollars` over the same set. The account's
        `margin_equity` is its `cash_balance` plus the sum of `unrealized_pnl`
        over all `OPEN` positions."
        PRD §3.5: "A `FUTURES_SHORT` position carries an initial margin of 0.30
        dollars per bushel and a maintenance margin of 0.22 dollars per bushel."
        (§2.10 carries the same rates.)

        Design: Difficulty/compensating_invariant/position_open_offset_conserve_margin_cash
        """
        ctx = _margin_ctx("Inv Farm 2", funding=20000)
        record_settlement_tick(4.50, "2026-06-01")
        rec = create_accepted_recommendation(ctx["plan"], ctx["operation"]["id"], bushels=10000)
        position = get_success_data(api.execute_recommendation(rec["id"], ADVISOR))
        opened = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert opened["cash_balance"] == pytest.approx(20000.00), "opening a futures position moves no cash"
        assert opened["initial_margin_required"] == pytest.approx(3000.00), "10000 bu * 0.30"
        offset = get_success_data(api.offset_position(position["id"], ADVISOR))
        assert offset["exit_price"] == pytest.approx(4.50), "exit at the unchanged latest SETTLEMENT"
        assert offset["realized_pnl"] == pytest.approx(0.00, abs=0.005)
        closed = get_success_data(api.get_margin_account(ctx["account"]["id"], ADVISOR))
        assert closed["cash_balance"] == pytest.approx(20000.00)
        assert closed["initial_margin_required"] == pytest.approx(0.00)
        assert closed["maintenance_margin_required"] == pytest.approx(0.00)
        assert closed["margin_equity"] == pytest.approx(20000.00), (
            "open + offset at an unchanged settlement conserves account value exactly"
        )

    def test_open_offset_pair_zero_pnl_at_unchanged_settlement(self, api):
        """PRD §3.5: "A position's `unrealized_pnl` is re-marked on every
        matching settlement tick. For `FUTURES_SHORT` it is the entry price
        minus the latest settlement price, multiplied by `bushels`."
        PRD §3.6: "`realized_pnl` is computed — for `FUTURES_SHORT`, the entry
        price minus the exit price multiplied by `bushels`".

        Design: Difficulty/compensating_invariant/position_open_offset_conserve_margin_cash
        """
        ctx = _margin_ctx("Inv Farm 2", funding=20000)
        record_settlement_tick(4.50, "2026-06-01")
        position = create_open_position(ctx, bushels=10000)
        marked = get_success_data(api.get_position(position["id"], ADVISOR))
        assert marked["unrealized_pnl"] == pytest.approx(0.00, abs=0.005), (
            "(entry 4.50 - latest 4.50) * 10000 == 0.00"
        )
        assert marked["entry_price"] == pytest.approx(4.50)
        offset = get_success_data(api.offset_position(position["id"], ADVISOR))
        assert offset["realized_pnl"] == pytest.approx(0.00, abs=0.005)
        assert offset["status"] == "OFFSET"
