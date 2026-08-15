"""Rebalance proposals, trade generation, compliance scan, execution, voids (PRD §3.5)."""
from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    ApiErrorId,
    add_position,
    assert_iso_instant_equal,
    create_active_client,
    create_active_ips,
    create_benchmark,
    create_portfolio_payload,
    create_rebalance_proposal_payload,
    create_restriction,
    create_security,
    deposit,
    generate_proposal,
    get_success_data,
    portfolio_version,
    proposal_trades,
    reprice,
    set_clock,
    setup_active_portfolio,
    setup_breached_60_40,
    validate_error,
    validate_paginated,
    validate_success,
)

T_60_40 = [
    {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
]
T_CASH = [
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
]


class TestProposalLifecycle:
    def test_proposal_cancel_and_terminal_lockdown(self, api):
        """PRD §3.5: "The advisor's parallel escape hatch, cancellation, moves
        `PROPOSED` or `NEEDS_REVISION` to `CANCELLED` with the same
        trade-cancel cascade."
        PRD §3.5: "Any of these transitions from a wrong from-state is rejected
        with `ERR_PROPOSAL_INVALID_STATE`."

        Design: Corner/state_machines/proposal_cancel_and_terminal_lockdown
        """
        fx = setup_breached_60_40(reprice_to=1500)
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        cancelled = validate_success(api.cancel_proposal(proposal["id"], ADVISOR))
        assert cancelled["status"] == "CANCELLED"
        trades = proposal_trades(proposal["id"], status="CANCELLED")
        assert len(trades) == 1, "its SELL trade was cancelled with the proposal"
        # CANCELLED is terminal.
        validate_error(api.approve_proposal(proposal["id"], COMPLIANCE),
                       ApiErrorId.ERR_PROPOSAL_INVALID_STATE)
        validate_error(api.cancel_proposal(proposal["id"], ADVISOR),
                       ApiErrorId.ERR_PROPOSAL_INVALID_STATE)

    def test_proposal_ttl_expiry_at_checkpoint_boundary(self, api):
        """PRD §3.5: "a `ComplianceOfficer`-run daily operations checkpoint
        expires every non-terminal proposal — `PROPOSED`, `NEEDS_REVISION`, or
        `APPROVED` — whose `expires_at` has been reached or passed by the
        logical clock, transitioning it to `EXPIRED` and cancelling its
        `PENDING` and `BLOCKED` trades, and reporting back
        `expired_proposal_count` together with the `expired_proposal_ids`."
        PRD §3.5: "stamps `generated_at` from the logical clock, and sets
        `expires_at` seven days later."

        Design: Corner/state_machines/proposal_ttl_expiry_at_checkpoint_boundary
        """
        fx = setup_breached_60_40(reprice_to=1500)
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        assert_iso_instant_equal(proposal["generated_at"], "2026-08-01T00:00:00Z")
        assert_iso_instant_equal(proposal["expires_at"], "2026-08-08T00:00:00Z")
        # One second before expiry: the proposal survives the checkpoint.
        set_clock("2026-08-07T23:59:59Z")
        report0 = validate_success(api.run_compliance_checkpoint(COMPLIANCE))
        assert report0["expired_proposal_count"] == 0
        assert validate_success(
            api.get_rebalance_proposal(proposal["id"], ADVISOR))["status"] == "PROPOSED"
        # At exactly expires_at the proposal has been reached.
        set_clock("2026-08-08T00:00:00Z")
        report1 = validate_success(api.run_compliance_checkpoint(COMPLIANCE))
        assert report1["expired_proposal_count"] == 1
        assert proposal["id"] in report1["expired_proposal_ids"]
        assert validate_success(
            api.get_rebalance_proposal(proposal["id"], ADVISOR))["status"] == "EXPIRED"
        assert len(proposal_trades(proposal["id"], status="CANCELLED")) == 1

    def test_proposal_superseded_by_newer_generation(self, api):
        """PRD §3.5: "Generation supersedes the portfolio's earlier open work:
        every existing proposal of the same portfolio in `PROPOSED` or
        `NEEDS_REVISION` transitions to `EXPIRED`, and its `PENDING` or
        `BLOCKED` trades transition to `CANCELLED`."
        PRD §3.5: "generation also increments the portfolio's `version`."

        Design: Corner/state_machines/proposal_superseded_by_newer_generation
        """
        fx = setup_breached_60_40(reprice_to=1500)
        p = fx["portfolio"]["id"]
        v1 = portfolio_version(p)
        g1 = generate_proposal(p, "DRIFT_BREACH")
        g2 = generate_proposal(p, "DRIFT_BREACH")
        assert g2["status"] == "PROPOSED"
        g1_after = validate_success(api.get_rebalance_proposal(g1["id"], ADVISOR))
        assert g1_after["status"] == "EXPIRED", "superseded by the newer generation"
        assert len(proposal_trades(g1["id"], status="CANCELLED")) == 1
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["version"] == v1 + 2, "one increment per generation"


class TestProposalGenerationGates:
    def test_occ_stale_portfolio_version_on_proposal_generate(self, api):
        """PRD §2.8: "If the portfolio's current `version` differs — because
        another writer has mutated the portfolio since the client last read
        it, for example by generating a proposal that superseded earlier ones
        — the generation is rejected with `ERR_STALE_PORTFOLIO_VERSION`
        (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_portfolio_version_on_proposal_generate
        """
        fx = setup_active_portfolio(targets=T_CASH)
        p = fx["portfolio"]["id"]
        deposit(p, 100000)
        observed = portfolio_version(p)
        g1 = validate_success(api.create_rebalance_proposal(
            create_rebalance_proposal_payload(p, observed, trigger_type="MANUAL"),
            ADVISOR), 201)
        # The generation bumped Portfolio.version; the same expected version
        # is now stale.
        validate_error(
            api.create_rebalance_proposal(
                create_rebalance_proposal_payload(p, observed, trigger_type="MANUAL"),
                ADVISOR),
            ApiErrorId.ERR_STALE_PORTFOLIO_VERSION)
        # Re-reading and resubmitting with the fresh version succeeds.
        g2 = validate_success(api.create_rebalance_proposal(
            create_rebalance_proposal_payload(p, portfolio_version(p),
                                              trigger_type="MANUAL"), ADVISOR), 201)
        assert validate_success(
            api.get_rebalance_proposal(g1["id"], ADVISOR))["status"] == "EXPIRED"
        rows, meta = validate_paginated(
            api.list_rebalance_proposals(ADVISOR, params={"portfolio_id": p}))
        assert meta["total_count"] == 2, "the 412 call created no proposal"
        assert {r["id"] for r in rows} == {g1["id"], g2["id"]}

    def test_drift_breach_trigger_requires_breached_status(self, api):
        """PRD §3.5: "a `DRIFT_BREACH` trigger is honored only while the
        portfolio's `drift_status` is `BREACHED`, else
        `ERR_DRIFT_NOT_BREACHED`"

        Design: Corner/validations/drift_breach_trigger_requires_breached_status
        """
        fx = setup_breached_60_40(reprice_to=None, client_name="DNB")
        p = fx["portfolio"]["id"]
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["drift_status"] == "WITHIN_BANDS"
        validate_error(
            api.create_rebalance_proposal(
                create_rebalance_proposal_payload(p, portfolio_version(p),
                                                  trigger_type="DRIFT_BREACH"),
                ADVISOR),
            ApiErrorId.ERR_DRIFT_NOT_BREACHED)
        # The same portfolio accepts a MANUAL trigger.
        manual = validate_success(api.create_rebalance_proposal(
            create_rebalance_proposal_payload(p, portfolio_version(p),
                                              trigger_type="MANUAL"), ADVISOR), 201)
        assert manual["status"] == "PROPOSED"

    def test_proposal_generation_requires_active_portfolio(self, api):
        """PRD §3.5: "The portfolio must be `ACTIVE`, else
        `ERR_PORTFOLIO_NOT_ACTIVE`"
        PRD §2.7: lifecycle state (category 7) precedes optimistic concurrency
        (category 8), so a correct version does not rescue the call.

        Design: Corner/validations/proposal_generation_requires_active_portfolio
        """
        client = create_active_client(full_name="OP", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        create_active_ips(client, bench, targets=T_CASH)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="P"), ADVISOR))
        assert portfolio["lifecycle_status"] == "OPEN"
        validate_error(
            api.create_rebalance_proposal(
                create_rebalance_proposal_payload(
                    portfolio["id"], portfolio["version"], trigger_type="MANUAL"),
                ADVISOR),
            ApiErrorId.ERR_PORTFOLIO_NOT_ACTIVE)

    def test_manual_proposal_on_balanced_portfolio_generates_zero_trades(self, api):
        """PRD §3.5: "For each class, the target value is `target_pct` times
        the total divided by 100, rounded half-up to integer cents before any
        class comparison; the class market value counts cash toward
        `CASH_EQUIVALENT`; and the class delta is target value minus class
        market value." — a portfolio exactly on target has a zero delta in
        every class, so no sell and no buy is emitted.

        Design: Corner/calculations/manual_proposal_on_balanced_portfolio_generates_zero_trades
        """
        fx = setup_breached_60_40(reprice_to=None, client_name="Bal")
        p = fx["portfolio"]["id"]
        proposal = generate_proposal(p, "MANUAL")
        assert proposal["total_buys_cents"] == 0
        assert proposal["total_sells_cents"] == 0
        assert proposal_trades(proposal["id"]) == []
        # Approve and execute succeed as no-ops and conserve the totals.
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        executed = validate_success(api.execute_proposal(proposal["id"], ADVISOR))
        assert executed["status"] == "EXECUTED"
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["total_value_cents"] == 1000000
        position = validate_success(api.get_position(fx["position"]["id"], ADVISOR))
        assert position["quantity"] == 600
        assert position["cost_basis_cents"] == 480000


class TestTradeGenerationMath:
    def _setup_rounding_fixture(self, api):
        """US 10.00/0.10 + CASH 90.00/5.00; cash 84964; EQ1/EQ2/EQ3 @1253 with
        1/1/10 zero-basis units. Total 100000; US 1504bps -> BREACHED."""
        fx = setup_active_portfolio(targets=[
            {"asset_class": "US_EQUITY", "target_pct": 10.00, "band_pct": 0.10},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 90.00, "band_pct": 5.00},
        ], client_name="Rounding Client")
        p = fx["portfolio"]["id"]
        deposit(p, 84964)
        s1 = create_security("EQ1", "US_EQUITY", 1253)
        s2 = create_security("EQ2", "US_EQUITY", 1253)
        s3 = create_security("EQ3", "US_EQUITY", 1253)
        add_position(p, s1["id"], 1, 0)
        add_position(p, s2["id"], 1, 0)
        add_position(p, s3["id"], 10, 0)
        fx["securities"] = {"EQ1": s1, "EQ2": s2, "EQ3": s3}
        return fx

    def test_rebalance_per_line_tax_rounding_reserve(self, api):
        """PRD §2.6: "When a tax amount is estimated, each line is rounded
        half-up to integer cents before any summation, and the aggregate is
        never re-rounded."
        Per line: round_half_up(1253 x 0.2) = 251, 251, and
        round_half_up(2506 x 0.2) = 501 -> reserve 1003 (aggregate rounding
        of 5012 x 0.2 would give 1002).

        Design: Difficulty/combinatorial_formula/rebalance_per_line_tax_rounding_mode_b
        """
        fx = self._setup_rounding_fixture(api)
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        assert proposal["est_tax_reserve_cents"] == 1003, (
            "per-line half-up rounding then sum: 251 + 251 + 501")
        assert proposal["total_sells_cents"] == 5012, (
            "1x1253 + 1x1253 + 2x1253; per-line floor leaves 24 cents dust")
        assert proposal["total_buys_cents"] == 0, (
            "no CASH_EQUIVALENT instruments exist; the shortfall stays in cash")
        assert proposal["cash_delta_cents"] == 4009, "5012 sells - 1003 reserve"

    def test_rebalance_per_line_quantities_floored(self, api):
        """PRD §3.5: "Quantities are floored per line first, and proceeds are
        summed afterward; the aggregate is never rounded."
        PRD §3.5: "Walking lots in rank order against the remaining overweight
        amount, each lot sells the smaller of its full `quantity` and the
        remaining amount divided by the security's current `price_cents`
        rounded down to whole units"

        Design: Difficulty/combinatorial_formula/rebalance_per_line_tax_rounding_mode_b
        """
        fx = self._setup_rounding_fixture(api)
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        trades = proposal_trades(proposal["id"])
        assert len(trades) == 3
        by_security = {t["security_id"]: t for t in trades}
        assert by_security[fx["securities"]["EQ1"]["id"]]["quantity"] == 1
        assert by_security[fx["securities"]["EQ2"]["id"]]["quantity"] == 1
        # floor(remaining 2530 / 1253) = 2 on the last lot.
        assert by_security[fx["securities"]["EQ3"]["id"]]["quantity"] == 2
        for trade in trades:
            assert trade["side"] == "SELL"
            assert trade["pinned_price_cents"] == 1253

    def _setup_waterfall_fixture(self, api):
        """US 5.00/1.00 + INTL 90.00/1.00 + CASH 5.00/1.00; cash 1000;
        EQZ 40 @1000 basis 20000 (US 97.56% -> BREACHED); EIB @500 unheld."""
        fx = setup_active_portfolio(targets=[
            {"asset_class": "US_EQUITY", "target_pct": 5.00, "band_pct": 1.00},
            {"asset_class": "INTL_EQUITY", "target_pct": 90.00, "band_pct": 1.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 5.00, "band_pct": 1.00},
        ], client_name="Waterfall Client")
        p = fx["portfolio"]["id"]
        deposit(p, 1000)
        eqz = create_security("EQZ", "US_EQUITY", 1000)
        eib = create_security("EIB", "INTL_EQUITY", 500)
        add_position(p, eqz["id"], 40, 20000)
        fx["securities"] = {"EQZ": eqz, "EIB": eib}
        return fx

    def test_waterfall_sells_and_tax_reserve(self, api):
        """PRD §3.5: "Sells are sized first, exactly as above, independent of
        tax. The estimated tax reserve is the sum over `SELL` lines of the same
        per-line formula as `est_tax_impact_cents` — each line rounded half-up
        before summing"
        Here: SELL 37 EQZ @ 1000 (relief 18500, gain 18500, reserve 3700).

        Design: Difficulty/combinatorial_formula/rebalance_waterfall_pinned_eval_order_mode_c
        """
        fx = self._setup_waterfall_fixture(api)
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        assert proposal["total_sells_cents"] == 37000
        assert proposal["est_tax_reserve_cents"] == 3700

    def test_waterfall_buys_trimmed_to_available_cash(self, api):
        """PRD §3.5: "The amount available for buys is current
        `cash_balance_cents` plus total sell proceeds minus the reserve. Buy
        trades are then trimmed in the fixed class order: walking the generated
        `BUY` instructions, while a buy's cost exceeds the remaining available
        amount, its quantity is reduced to the remaining amount divided by its
        pinned price rounded down, and a trade whose quantity floors to zero is
        dropped. Sells are never recomputed after the reserve is known."
        Available = 1000 + 37000 - 3700 = 34300, so the EIB buy trims to
        floor(34300/500) = 68 units (34000), not the untrimmed 73.

        Design: Difficulty/combinatorial_formula/rebalance_waterfall_pinned_eval_order_mode_c
        """
        fx = self._setup_waterfall_fixture(api)
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        assert proposal["total_buys_cents"] == 34000
        assert proposal["cash_delta_cents"] == -700
        buys = [t for t in proposal_trades(proposal["id"]) if t["side"] == "BUY"]
        assert len(buys) == 1
        assert buys[0]["security_id"] == fx["securities"]["EIB"]["id"]
        assert buys[0]["quantity"] == 68

    def test_buy_selector_price_rank_then_created_at_tiebreak(self, api):
        """PRD §3.5: "candidates are securities of the class that are `LISTED`
        and not blocked from buying by any `ACTIVE` restricted-list entry,
        ranked by `price_cents` ascending with ties broken by `created_at`
        ascending; the first-ranked security receives a `BUY` for the delta
        divided by its price, rounded down, emitted only when that is at least
        one unit."

        Design: Corner/calculations/buy_selector_price_rank_then_created_at_tiebreak
        """
        fx = setup_active_portfolio(targets=[
            {"asset_class": "US_EQUITY", "target_pct": 50.00, "band_pct": 5.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 50.00, "band_pct": 5.00},
        ], tax_status="TAX_DEFERRED", client_name="Sel")
        p = fx["portfolio"]["id"]
        deposit(p, 100000)
        buz = create_security("BUZ", "US_EQUITY", 1000)  # earliest created_at
        bqy = create_security("BQY", "US_EQUITY", 1000)
        create_security("BQX", "US_EQUITY", 1000)
        # Generation 1: all candidates @1000 — the tie breaks to the earliest.
        g1 = generate_proposal(p, "DRIFT_BREACH")
        trades1 = proposal_trades(g1["id"])
        assert len(trades1) == 1
        assert trades1[0]["side"] == "BUY"
        assert trades1[0]["security_id"] == buz["id"]
        assert trades1[0]["quantity"] == 50, "floor(50000/1000)"
        # Generation 2: after BQY is repriced to 900 it is the cheapest.
        reprice(bqy["id"], 900)
        g2 = generate_proposal(p, "DRIFT_BREACH")
        trades2 = proposal_trades(g2["id"])
        assert len(trades2) == 1
        assert trades2[0]["security_id"] == bqy["id"]
        assert trades2[0]["quantity"] == 55, "floor(50000/900)"
        assert validate_success(
            api.get_rebalance_proposal(g1["id"], ADVISOR))["status"] == "EXPIRED"
        # No trade is emitted for the CASH_EQUIVALENT sleeve in either
        # generation — each proposal produced exactly the single US_EQUITY buy.


class TestRevisionCycle:
    def _setup_cycle(self, api):
        fx = setup_breached_60_40(reprice_to=1500, client_name="Cycle Client")
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        assert proposal["total_sells_cents"] == 120000, "SELL 80 @ 1500"
        return fx, proposal

    def test_revision_returns_to_proposed_with_new_totals(self, api):
        """PRD §3.5: "Revision cancels every `PENDING` or `BLOCKED` trade of
        the proposal, regenerates the full trade list at current prices through
        the generation and waterfall rules above, recomputes
        `total_buys_cents`, `total_sells_cents`, `est_tax_reserve_cents`, and
        `cash_delta_cents`, refreshes `pinned_ips_version` to the IPS's current
        `version`, and resets `expires_at` to seven days from the present —
        returning the proposal to `PROPOSED`."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_regenerates_trades
        """
        fx, proposal = self._setup_cycle(api)
        get_success_data(api.request_changes_proposal(proposal["id"], COMPLIANCE,
                                                      reason="resize"))
        reprice(fx["security"]["id"], 1550)
        revised = validate_success(api.revise_proposal(proposal["id"], ADVISOR))
        assert revised["status"] == "PROPOSED", "the cycle completed"
        assert revised["total_sells_cents"] == 131750, (
            "SELL 85 @ 1550 — regenerated at current prices, not the old 120000")
        assert revised["est_tax_reserve_cents"] == 12750, (
            "relief 68000, gain 63750, 20%")

    def test_revision_cancels_old_trades_and_regenerates(self, api):
        """PRD §3.5: "Revision cancels every `PENDING` or `BLOCKED` trade of
        the proposal, regenerates the full trade list at current prices"

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_regenerates_trades
        """
        fx, proposal = self._setup_cycle(api)
        get_success_data(api.request_changes_proposal(proposal["id"], COMPLIANCE,
                                                      reason="resize"))
        reprice(fx["security"]["id"], 1550)
        get_success_data(api.revise_proposal(proposal["id"], ADVISOR))
        pending = proposal_trades(proposal["id"], status="PENDING")
        assert len(pending) == 1
        assert pending[0]["quantity"] == 85
        assert pending[0]["pinned_price_cents"] == 1550
        cancelled = proposal_trades(proposal["id"], status="CANCELLED")
        assert len(cancelled) == 1, "the original SELL-80 trade is CANCELLED"
        assert cancelled[0]["quantity"] == 80
        assert cancelled[0]["pinned_price_cents"] == 1500


class TestExecutionConservation:
    def _setup_conservation_fixture(self, api):
        fx = setup_active_portfolio(targets=[
            {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
            {"asset_class": "INTL_EQUITY", "target_pct": 10.00, "band_pct": 5.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 30.00, "band_pct": 5.00},
        ], tax_status="TAX_DEFERRED", client_name="Conserve Client")
        p = fx["portfolio"]["id"]
        deposit(p, 300000)
        eqa = create_security("EQA", "US_EQUITY", 1000)
        eib = create_security("EIB", "INTL_EQUITY", 500)
        pos = add_position(p, eqa["id"], 600, 480000)
        fx.update({"securities": {"EQA": eqa, "EIB": eib}, "position": pos})
        proposal = generate_proposal(p, "DRIFT_BREACH")
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        return fx, proposal

    def test_sell_buy_pair_execution_conserves_total_value(self, api):
        """PRD §2.9: "A portfolio's `total_value_cents` is `cash_balance_cents`
        plus the sum of `market_value_cents` over its positions."
        Executing the SELL 60 EQA + BUY 180 EIB pair at current prices moves
        cash through positions and back, leaving total_value_cents at 900000.

        Design: Difficulty/compensating_invariant/sell_buy_pair_execution_conserves_total_value
        """
        fx, proposal = self._setup_conservation_fixture(api)
        p = fx["portfolio"]["id"]
        pre = validate_success(api.get_portfolio(p, ADVISOR))
        assert pre["total_value_cents"] == 900000
        executed = validate_success(api.execute_proposal(proposal["id"], ADVISOR))
        assert executed["status"] == "EXECUTED"
        post = validate_success(api.get_portfolio(p, ADVISOR))
        assert post["total_value_cents"] == 900000, (
            "conserved across the sell/buy pair")
        assert post["cash_balance_cents"] == 270000, "300000 + 60000 - 90000"
        assert post["drift_status"] == "WITHIN_BANDS", (
            "the plan fully covered the breach")

    def test_sell_buy_pair_execution_positions_and_ledger(self, api):
        """PRD §3.5: "Execution fills every `PENDING` trade at the security's
        current `price_cents`, never the pinned estimate, in a deterministic
        ledger order: all `SELL` trades first in the fixed class order, then
        all `BUY` trades in the fixed class order, with ties inside a class
        broken by the trade's `created_at` ascending; ledger events append in
        exactly that execution order."

        Design: Difficulty/compensating_invariant/sell_buy_pair_execution_conserves_total_value
        """
        fx, proposal = self._setup_conservation_fixture(api)
        p = fx["portfolio"]["id"]
        validate_success(api.execute_proposal(proposal["id"], ADVISOR))
        # SELL 60 EQA @ 1000: relief 48000, gain 12000.
        position = validate_success(api.get_position(fx["position"]["id"], ADVISOR))
        assert position["quantity"] == 540
        assert position["cost_basis_cents"] == 432000
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["lifetime_realized_gains_cents"] == 12000
        # BUY 180 EIB @ 500 opens a new lot at cost.
        rows, _ = validate_paginated(api.list_positions(
            ADVISOR, params={"portfolio_id": p,
                             "security_id": fx["securities"]["EIB"]["id"]}))
        assert len(rows) == 1
        assert rows[0]["quantity"] == 180
        assert rows[0]["cost_basis_cents"] == 90000
        # Exactly two TRADE_EXECUTION events, SELL (+60000) before BUY
        # (-90000): the running balance_after pins the ledger order.
        events, _ = validate_paginated(api.list_cash_flow_events(
            ADVISOR, params={"portfolio_id": p, "kind": "TRADE_EXECUTION"}))
        assert len(events) == 2
        by_amount = {e["amount_cents"]: e for e in events}
        assert by_amount[60000]["balance_after_cents"] == 360000, (
            "the SELL proceeds landed first")
        assert by_amount[-90000]["balance_after_cents"] == 270000, (
            "the BUY cost settled second")
        assert all(e["source_type"] == "TRADE" for e in events)


class TestTradeVoid:
    def _setup_executed_sell(self, api):
        fx = setup_breached_60_40(reprice_to=1500, client_name="Void Client")
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        trade = proposal_trades(proposal["id"])[0]
        return fx, proposal, trade

    def test_trade_void_state_and_window_guards(self, api):
        """PRD §3.5: "the trade must be `EXECUTED` (else
        `ERR_TRADE_INVALID_STATE`), and the UTC date of the current logical
        clock must equal the UTC date of the trade's `executed_at`, else
        `ERR_TRADE_VOID_WINDOW_EXPIRED`."

        Design: Corner/state_machines/trade_void_state_and_window_guards
        """
        fx, proposal, trade = self._setup_executed_sell(api)
        # Void of a PENDING trade: wrong from-state.
        validate_error(api.void_trade(trade["id"], COMPLIANCE),
                       ApiErrorId.ERR_TRADE_INVALID_STATE)
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        get_success_data(api.execute_proposal(proposal["id"], ADVISOR))
        # Next UTC day: the same-day window has closed.
        set_clock("2026-08-02T00:00:00Z")
        validate_error(api.void_trade(trade["id"], COMPLIANCE),
                       ApiErrorId.ERR_TRADE_VOID_WINDOW_EXPIRED)
        assert validate_success(
            api.get_trade_instruction(trade["id"], ADVISOR))["status"] == "EXECUTED"

    def test_execute_then_void_restores_position_and_basis(self, api):
        """PRD §3.5: "Voiding a `SELL` restores the sold units to the position,
        restores exactly the relief cents recorded at execution to
        `cost_basis_cents`, and pulls the proceeds back out of cash through a
        `TRADE_VOID` event"
        After execution the position stood at 520 units / 416000 basis; the
        same-day void returns it to 600 / 480000.

        Design: Difficulty/compensating_invariant/execute_then_void_restores_quantity_basis_cash
        """
        fx, proposal, trade = self._setup_executed_sell(api)
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        get_success_data(api.execute_proposal(proposal["id"], ADVISOR))
        mid = validate_success(api.get_position(fx["position"]["id"], ADVISOR))
        assert mid["quantity"] == 520
        assert mid["cost_basis_cents"] == 416000, "relief 64000 drawn at execution"
        voided = validate_success(api.void_trade(trade["id"], COMPLIANCE))
        assert voided["status"] == "VOIDED"
        assert voided["voided_at"] is not None
        position = validate_success(api.get_position(fx["position"]["id"], ADVISOR))
        assert position["quantity"] == 600, "sold units restored exactly"
        assert position["cost_basis_cents"] == 480000, "relief 64000 returned exactly"

    def test_execute_then_void_restores_cash(self, api):
        """PRD §3.5: "Either way the net effect returns `quantity`,
        `cost_basis_cents`, and `cash_balance_cents` to their pre-execution
        values"

        Design: Difficulty/compensating_invariant/execute_then_void_restores_quantity_basis_cash
        """
        fx, proposal, trade = self._setup_executed_sell(api)
        p = fx["portfolio"]["id"]
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        get_success_data(api.execute_proposal(proposal["id"], ADVISOR))
        mid = validate_success(api.get_portfolio(p, ADVISOR))
        assert mid["cash_balance_cents"] == 520000, "+120000 execution proceeds"
        get_success_data(api.void_trade(trade["id"], COMPLIANCE))
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["cash_balance_cents"] == 400000, (
            "the TRADE_VOID event of -120000 reverses the execution event")
        events, _ = validate_paginated(api.list_cash_flow_events(
            ADVISOR, params={"portfolio_id": p, "kind": "TRADE_VOID"}))
        assert len(events) == 1
        assert events[0]["amount_cents"] == -120000
        assert events[0]["source_type"] == "TRADE"
        assert events[0]["source_id"] == trade["id"]
        # The proposal itself is untouched by the void.
        assert validate_success(
            api.get_rebalance_proposal(proposal["id"], ADVISOR))["status"] == "EXECUTED"


class TestComplianceScanAndExecuteGates:
    def test_blocked_trade_gate_release_then_execute(self, api):
        """PRD §3.5: "every `PENDING` trade whose security has an `ACTIVE`
        restriction blocking its side, or whose security is no longer `LISTED`,
        transitions to `BLOCKED`."
        PRD §3.5: "no trade of the proposal may stand in `BLOCKED`, else
        `ERR_TRADES_BLOCKED`"
        PRD §3.5: "the trade must be `BLOCKED` (else `ERR_TRADE_INVALID_STATE`),
        no `ACTIVE` restricted-list entry may block its side (else
        `ERR_SECURITY_RESTRICTED`), the security must be `LISTED` (else
        `ERR_SECURITY_NOT_TRADEABLE`), and the owning proposal must stand in
        `APPROVED` (else `ERR_PROPOSAL_INVALID_STATE`)"

        Design: Corner/state_machines/proposal_blocked_trade_gate_release_then_execute
        """
        fx = setup_breached_60_40(reprice_to=1500, client_name="Blocked")
        p = fx["portfolio"]["id"]
        proposal = generate_proposal(p, "DRIFT_BREACH")
        entry = create_restriction(fx["security"]["id"], level="NO_TRADE",
                                   effective_from="2026-08-01T00:00:00Z",
                                   effective_to="2026-09-01T00:00:00Z")
        # Approve-time compliance scan blocks the restricted SELL.
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        trades = proposal_trades(proposal["id"])
        assert len(trades) == 1
        trade = trades[0]
        assert trade["status"] == "BLOCKED"
        # Execute is gated while any trade is BLOCKED; nothing settles.
        validate_error(api.execute_proposal(proposal["id"], ADVISOR),
                       ApiErrorId.ERR_TRADES_BLOCKED)
        assert validate_success(api.get_portfolio(p, ADVISOR))[
            "cash_balance_cents"] == 400000
        # Release fails while the restriction is ACTIVE.
        validate_error(api.release_trade(trade["id"], COMPLIANCE),
                       ApiErrorId.ERR_SECURITY_RESTRICTED)
        # After termination the release succeeds and execution fills at the
        # current price.
        get_success_data(api.terminate_restricted_list_entry(entry["id"], COMPLIANCE))
        released = validate_success(api.release_trade(trade["id"], COMPLIANCE))
        assert released["status"] == "PENDING"
        executed = validate_success(api.execute_proposal(proposal["id"], ADVISOR))
        assert executed["status"] == "EXECUTED"
        position = validate_success(api.get_position(fx["position"]["id"], ADVISOR))
        assert position["quantity"] == 520
        assert validate_success(api.get_portfolio(p, ADVISOR))[
            "cash_balance_cents"] == 520000

    def test_execute_frozen_state_error_beats_safety_error(self, api):
        """PRD §2.7: "Checks run in a fixed priority order, and when several
        checks would fail, the request is rejected with the error from the
        earliest category" — lifecycle state (7) precedes the compliance gates
        (9).
        PRD §3.5: "the portfolio must be `ACTIVE`, else
        `ERR_PORTFOLIO_NOT_ACTIVE`"

        Design: Difficulty/priority_pair_validation_conflict/execute_frozen_with_restricted_trade_state_beats_safety
        """
        fx = setup_breached_60_40(reprice_to=1500, client_name="Prio Client")
        p = fx["portfolio"]["id"]
        proposal = generate_proposal(p, "DRIFT_BREACH")
        # Approved while unrestricted: the scan blocks nothing.
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        # Now the trade's security becomes restricted AND the portfolio freezes.
        create_restriction(fx["security"]["id"], level="NO_TRADE",
                           effective_from="2026-08-01T00:00:00Z",
                           effective_to="2026-09-01T00:00:00Z",
                           reason="investigation")
        get_success_data(api.freeze_portfolio(p, COMPLIANCE))
        # Both conditions hold; the state error (earlier category) is reported.
        validate_error(api.execute_proposal(proposal["id"], ADVISOR),
                       ApiErrorId.ERR_PORTFOLIO_NOT_ACTIVE)

    def test_execute_frozen_leaves_no_side_effects(self, api):
        """PRD §3.5: "the portfolio must be `ACTIVE`, else
        `ERR_PORTFOLIO_NOT_ACTIVE`" — the rejected execute mutates nothing.

        Design: Difficulty/priority_pair_validation_conflict/execute_frozen_with_restricted_trade_state_beats_safety
        """
        fx = setup_breached_60_40(reprice_to=1500, client_name="Prio Client")
        p = fx["portfolio"]["id"]
        proposal = generate_proposal(p, "DRIFT_BREACH")
        get_success_data(api.approve_proposal(proposal["id"], COMPLIANCE))
        create_restriction(fx["security"]["id"], level="NO_TRADE",
                           effective_from="2026-08-01T00:00:00Z",
                           effective_to="2026-09-01T00:00:00Z")
        get_success_data(api.freeze_portfolio(p, COMPLIANCE))
        validate_error(api.execute_proposal(proposal["id"], ADVISOR),
                       ApiErrorId.ERR_PORTFOLIO_NOT_ACTIVE)
        after = validate_success(api.get_rebalance_proposal(proposal["id"], ADVISOR))
        assert after["status"] == "APPROVED", "the proposal is unchanged"
        assert validate_success(api.get_portfolio(p, ADVISOR))[
            "cash_balance_cents"] == 400000
        assert proposal_trades(proposal["id"], status="EXECUTED") == []


class TestPinnedVersionRecovery:
    def test_version_pin_stale_detection_and_recovery_via_revise(self, api):
        """PRD §3.5: "the pinned policy must still be current — the pinned IPS
        still `ACTIVE` and `pinned_ips_version` still equal to the IPS's
        current `version` — else `ERR_PROPOSAL_STALE_PIN`."
        PRD §3.5: "Revision cancels every `PENDING` or `BLOCKED` trade of the
        proposal, regenerates the full trade list at current prices through the
        generation and waterfall rules above, recomputes `total_buys_cents`,
        `total_sells_cents`, `est_tax_reserve_cents`, and `cash_delta_cents`,
        refreshes `pinned_ips_version` to the IPS's current `version`, and
        resets `expires_at` to seven days from the present — returning the
        proposal to `PROPOSED`."

        Design: Corner/complexity_layers/version_pin_stale_detection_and_recovery_via_revise
        """
        fx = setup_breached_60_40(reprice_to=1500, client_name="Pin")
        proposal = generate_proposal(fx["portfolio"]["id"], "DRIFT_BREACH")
        pinned = proposal["pinned_ips_version"]
        # A completed review mutates the IPS, advancing its version.
        get_success_data(api.complete_review_ips(fx["ips"]["id"], ADVISOR))
        ips_now = validate_success(api.get_ips(fx["ips"]["id"], ADVISOR))
        assert ips_now["version"] > pinned
        # Approve against the stale pin is rejected.
        validate_error(api.approve_proposal(proposal["id"], COMPLIANCE),
                       ApiErrorId.ERR_PROPOSAL_STALE_PIN)
        # Recovery through the revision cycle refreshes the pin.
        get_success_data(api.request_changes_proposal(proposal["id"], COMPLIANCE,
                                                      reason="refresh pin"))
        revised = validate_success(api.revise_proposal(proposal["id"], ADVISOR))
        assert revised["pinned_ips_version"] == ips_now["version"]
        approved = validate_success(api.approve_proposal(proposal["id"], COMPLIANCE))
        assert approved["status"] == "APPROVED"
