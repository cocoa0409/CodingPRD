"""Portfolio lifecycle, cash ledger, drift boundaries, and listing (PRD §2.3, §2.9, §3.4, §3.5)."""
from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    ApiErrorId,
    add_position,
    allocation_targets_payload,
    assert_cash_flow_event,
    create_active_client,
    create_active_ips,
    create_benchmark,
    create_ips_payload,
    create_portfolio_payload,
    create_security,
    deposit,
    get_success_data,
    make_client_headers,
    reprice,
    setup_active_portfolio,
    setup_breached_60_40,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_cash,
)

T_CASH = [
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
]
T_US_ONLY = [
    {"asset_class": "US_EQUITY", "target_pct": 100.00, "band_pct": 50.00},
]


class TestPortfolioLifecycle:
    def test_activation_gated_until_client_signs_ips(self, api):
        """PRD §3.4: "the client must hold an `ACTIVE` IPS (else
        `ERR_NO_ACTIVE_IPS`)"

        Design: Difficulty/cross_entity_state_dependency/portfolio_activation_gated_by_active_ips
        """
        client = create_active_client(full_name="Gate2 Client",
                                      risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="Early"), ADVISOR))
        bench = create_benchmark(name="Bench")
        ips = get_success_data(api.create_ips(
            create_ips_payload(client["id"], bench["id"], objective_text="Growth",
                               risk_tolerance_score=50), ADVISOR))
        get_success_data(api.replace_allocation_targets(
            ips["id"], allocation_targets_payload([
                {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
                {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00,
                 "band_pct": 5.00},
            ]), ADVISOR))
        get_success_data(api.submit_ips(ips["id"], ADVISOR))
        get_success_data(api.compliance_approve_ips(ips["id"], COMPLIANCE))
        # IPS only PENDING_CLIENT at this point.
        validate_error(api.activate_portfolio(portfolio["id"], ADVISOR),
                       ApiErrorId.ERR_NO_ACTIVE_IPS)

    def test_activation_succeeds_after_ips_active(self, api):
        """PRD §3.4: "Activation runs the drift assessment immediately so the
        portfolio enters service with a fresh `drift_status`."
        PRD §3.5: "If the total is zero, the status is `WITHIN_BANDS` and
        evaluation stops."

        Design: Difficulty/cross_entity_state_dependency/portfolio_activation_gated_by_active_ips
        """
        client = create_active_client(full_name="Gate2 Client",
                                      risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="Early"), ADVISOR))
        bench = create_benchmark(name="Bench")
        create_active_ips(client, bench, targets=[
            {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
        ])
        activated = validate_success(api.activate_portfolio(portfolio["id"], ADVISOR))
        assert activated["lifecycle_status"] == "ACTIVE"
        assert activated["drift_status"] == "WITHIN_BANDS", (
            "total 0 is vacuously within bands")

    def test_portfolio_freeze_gates_operations_and_invalid_unfreeze(self, api):
        """PRD §3.4: "While a portfolio is not `ACTIVE`, the operational
        surface closes: creating positions, recording cash movements,
        generating, approving, revising, or executing proposals, and modeling,
        approving, or settling withdrawals are all rejected with
        `ERR_PORTFOLIO_NOT_ACTIVE`."
        PRD §3.4: "either transition from a wrong from-state is rejected with
        `ERR_PORTFOLIO_INVALID_STATE`."

        Design: Corner/state_machines/portfolio_freeze_gates_operations_and_invalid_unfreeze
        """
        fx = setup_active_portfolio(targets=T_CASH)
        p = fx["portfolio"]["id"]
        deposit(p, 100000)
        security = create_security("EQA", "US_EQUITY", 1000)
        # Unfreeze from ACTIVE: invalid transition.
        validate_error(api.unfreeze_portfolio(p, COMPLIANCE),
                       ApiErrorId.ERR_PORTFOLIO_INVALID_STATE)
        get_success_data(api.freeze_portfolio(p, COMPLIANCE))
        # While FROZEN, the operational surface closes.
        validate_error(
            api.create_position({"portfolio_id": p, "security_id": security["id"],
                                 "quantity": 10, "opening_cost_basis_cents": 10000},
                                ADVISOR),
            ApiErrorId.ERR_PORTFOLIO_NOT_ACTIVE)
        validate_error(
            api.create_cash_movement(p, {"direction": "DEPOSIT", "amount_cents": 1,
                                         "occurred_at": "2026-08-01T00:00:00Z"},
                                     ADVISOR),
            ApiErrorId.ERR_PORTFOLIO_NOT_ACTIVE)
        # Unfreeze restores operability (ACTIVE -> FROZEN -> ACTIVE).
        get_success_data(api.unfreeze_portfolio(p, COMPLIANCE))
        position = validate_success(
            api.create_position({"portfolio_id": p, "security_id": security["id"],
                                 "quantity": 10, "opening_cost_basis_cents": 10000},
                                ADVISOR), 201)
        assert position["quantity"] == 10

    def test_portfolio_close_guards_and_terminal_lockdown(self, api):
        """PRD §3.4: "An `Advisor` closes an `ACTIVE` portfolio only when every
        position stands at zero units and `cash_balance_cents` is zero, else
        `ERR_PORTFOLIO_NOT_EMPTY`, and only when no withdrawal request stands
        in `SUBMITTED`, `MODELED`, or `APPROVED` and no rebalance proposal
        stands in `PROPOSED`, `NEEDS_REVISION`, or `APPROVED`, else
        `ERR_OPEN_WORK_ITEMS`."
        PRD §3.4: "Closure moves `ACTIVE → CLOSED` and sets `drift_status` to
        `WITHIN_BANDS` — vacuously true, since the account is worth nothing."

        Design: Corner/state_machines/portfolio_close_guards_and_terminal_lockdown
        """
        fx = setup_active_portfolio(targets=T_CASH)
        p = fx["portfolio"]["id"]
        client = fx["client"]
        deposit(p, 100000)
        # Non-zero cash blocks closure.
        validate_error(api.close_portfolio(p, ADVISOR),
                       ApiErrorId.ERR_PORTFOLIO_NOT_EMPTY)
        withdraw_cash(p, 100000)
        # An open (SUBMITTED) withdrawal blocks closure.
        w = get_success_data(api.create_withdrawal_request(
            {"portfolio_id": p, "amount_cents": 1, "funding_mode": "CASH_FIRST"},
            ADVISOR))
        validate_error(api.close_portfolio(p, ADVISOR),
                       ApiErrorId.ERR_OPEN_WORK_ITEMS)
        # After the owner cancels, closure succeeds.
        get_success_data(api.cancel_withdrawal(w["id"], make_client_headers(client["id"])))
        closed = validate_success(api.close_portfolio(p, ADVISOR))
        assert closed["lifecycle_status"] == "CLOSED"
        assert closed["drift_status"] == "WITHIN_BANDS"
        # CLOSED is terminal.
        validate_error(api.freeze_portfolio(p, COMPLIANCE),
                       ApiErrorId.ERR_PORTFOLIO_INVALID_STATE)


class TestParallelDriftDimension:
    def test_freeze_preserves_drift_status(self, api):
        """PRD §2.10: "A drift transition never alters `lifecycle_status`, and
        a lifecycle transition never alters `drift_status` except where a
        specific rule says so"

        Design: Difficulty/non_linear_state_machine/portfolio_parallel_drift_dimension_independence
        """
        fx = setup_breached_60_40(reprice_to=1500)
        p = fx["portfolio"]["id"]
        before = validate_success(api.get_portfolio(p, ADVISOR))
        assert before["lifecycle_status"] == "ACTIVE"
        assert before["drift_status"] == "BREACHED", "US ~69.2% vs 60% target"
        frozen = validate_success(api.freeze_portfolio(p, COMPLIANCE))
        assert frozen["lifecycle_status"] == "FROZEN"
        reread = validate_success(api.get_portfolio(p, ADVISOR))
        assert reread["drift_status"] == "BREACHED", (
            "freeze leaves the drift dimension untouched")

    def test_reprice_while_frozen_flips_drift_only(self, api):
        """PRD §2.10: "`drift_status` — `UNTRACKED`, `WITHIN_BANDS`, or
        `BREACHED` — is computed by the drift assessment of §3.5 and changes
        only in response to market, ledger, or policy events."

        Design: Difficulty/non_linear_state_machine/portfolio_parallel_drift_dimension_independence
        """
        fx = setup_breached_60_40(reprice_to=1500)
        p = fx["portfolio"]["id"]
        get_success_data(api.freeze_portfolio(p, COMPLIANCE))
        # Reprice back to 1000 while FROZEN: the computed dimension moves.
        reprice(fx["security"]["id"], 1000)
        frozen = validate_success(api.get_portfolio(p, ADVISOR))
        assert frozen["lifecycle_status"] == "FROZEN"
        assert frozen["drift_status"] == "WITHIN_BANDS"
        unfrozen = validate_success(api.unfreeze_portfolio(p, COMPLIANCE))
        assert unfrozen["lifecycle_status"] == "ACTIVE"
        assert unfrozen["drift_status"] == "WITHIN_BANDS"


class TestDriftBoundary:
    def test_drift_exactly_at_band_edge_is_not_a_breach(self, api):
        """PRD §3.5: "A class breaches when its actual weight differs from its
        target weight by strictly more than the band — equality with the band
        edge is not a breach."

        Design: Difficulty/boundary_precision_check/drift_band_equality_is_not_a_breach
        """
        fx = setup_active_portfolio(targets=[
            {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
        ], client_name="Boundary Client")
        p = fx["portfolio"]["id"]
        deposit(p, 350000)
        security = create_security("EQA", "US_EQUITY", 1000)
        add_position(p, security["id"], 650, 520000)
        # US 650000 of 1000000 = 6500bps vs target 6000: drift 500 == band 500.
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["total_value_cents"] == 1000000
        assert portfolio["drift_status"] == "WITHIN_BANDS", (
            "strict >: equality with the band edge is not a breach")

    def test_drift_one_cent_past_band_edge_breaches(self, api):
        """PRD §3.5: "A class breaches when its actual weight differs from its
        target weight by strictly more than the band — equality with the band
        edge is not a breach."

        Design: Difficulty/boundary_precision_check/drift_band_equality_is_not_a_breach
        """
        fx = setup_active_portfolio(targets=[
            {"asset_class": "US_EQUITY", "target_pct": 60.00, "band_pct": 5.00},
            {"asset_class": "CASH_EQUIVALENT", "target_pct": 40.00, "band_pct": 5.00},
        ], client_name="Boundary Client")
        p = fx["portfolio"]["id"]
        deposit(p, 350000)
        security = create_security("EQA", "US_EQUITY", 1000)
        add_position(p, security["id"], 650, 520000)
        # One cent more per unit: US 6502bps, drift 502 > 500.
        reprice(security["id"], 1001)
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["drift_status"] == "BREACHED"


class TestCashLedger:
    def test_manual_cash_withdrawal_capped_at_balance_with_equality(self, api):
        """PRD §3.4: "a withdrawal appends a `MANUAL_WITHDRAWAL` event with a
        negative signed amount and is permitted only while the amount does not
        exceed the current `cash_balance_cents`, else `ERR_INSUFFICIENT_CASH`."

        Design: Corner/validations/manual_cash_withdrawal_capped_at_balance_with_equality
        """
        fx = setup_active_portfolio(targets=T_CASH)
        p = fx["portfolio"]["id"]
        deposit(p, 100000)
        # One cent over the balance is rejected.
        validate_error(
            api.create_cash_movement(p, {"direction": "WITHDRAWAL",
                                         "amount_cents": 100001,
                                         "occurred_at": "2026-08-01T00:00:00Z"},
                                     ADVISOR),
            ApiErrorId.ERR_INSUFFICIENT_CASH)
        # Exactly the balance succeeds and zeroes the sleeve.
        event = validate_success(
            api.create_cash_movement(p, {"direction": "WITHDRAWAL",
                                         "amount_cents": 100000,
                                         "occurred_at": "2026-08-01T00:00:00Z"},
                                     ADVISOR), 201)
        assert event["balance_after_cents"] == 0

    def test_default_logical_clock_proven_by_event_futurity(self, api):
        """PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`; before any operator sets it, the logical clock
        reads that default and never the wall clock."
        PRD §3.4: "the flow may be backdated but never future-dated — an
        `occurred_at` later than the current logical clock is rejected with
        `ERR_EVENT_IN_FUTURE`."

        Design: Corner/endpoints/default_logical_clock_proven_by_event_futurity
        """
        fx = setup_active_portfolio(targets=T_CASH)
        p = fx["portfolio"]["id"]
        # No set-clock call has been made; equality with the default is allowed.
        event = validate_success(
            api.create_cash_movement(p, {"direction": "DEPOSIT", "amount_cents": 1000,
                                         "occurred_at": "2026-08-01T00:00:00Z"},
                                     ADVISOR), 201)
        assert event["kind"] == "MANUAL_DEPOSIT"
        # One second later than the default clock is future-dated.
        validate_error(
            api.create_cash_movement(p, {"direction": "DEPOSIT", "amount_cents": 1000,
                                         "occurred_at": "2026-08-01T00:00:01Z"},
                                     ADVISOR),
            ApiErrorId.ERR_EVENT_IN_FUTURE)

    def test_ledger_arrival_order_with_backdated_events(self, api):
        """PRD §2.9: "Ledger order is arrival (append) order. The `occurred_at`
        value — which may be backdated — influences reporting windows only and
        never reorders the ledger; `balance_after_cents` is always computed at
        append time from the prior ledger tip."
        PRD §2.9: "A portfolio's `cash_balance_cents` at any moment is the sum
        of `amount_cents` across its events, with immediate consistency after
        every append."

        Design: Corner/complexity_layers/derived_cash_balance_reconciles_with_event_ledger_arrival_order
        """
        fx = setup_active_portfolio(targets=T_CASH)
        p = fx["portfolio"]["id"]
        e1 = deposit(p, 50000, "2026-08-01T00:00:00Z")
        assert e1["balance_after_cents"] == 50000
        assert e1["valuation_before_cents"] == 0
        # Backdated: appended second, so the running balance does not reorder.
        e2 = deposit(p, 50000, "2026-07-15T00:00:00Z")
        assert e2["balance_after_cents"] == 100000
        assert e2["valuation_before_cents"] == 50000
        e3 = withdraw_cash(p, 30000, "2026-07-20T00:00:00Z")
        assert e3["balance_after_cents"] == 70000
        assert e3["valuation_before_cents"] == 100000
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["cash_balance_cents"] == 70000, (
            "projection equals the signed event sum")

    def test_cashflow_event_immutability_common_fields_false(self, api):
        """PRD §2.4: "A `CashFlowEvent` is an immutable append-only record and
        carries only `id` and `created_at` from the standard set; it has no
        `updated_at` and no `version`."
        PRD §3.4: "Either direction records `balance_after_cents`,
        `valuation_before_cents`, a `source_type` of `MANUAL`, and a null
        `source_id` on the event"

        Design: Corner/entities/cashflow_event_immutability_common_fields_false
        """
        fx = setup_active_portfolio(targets=T_CASH)
        event = deposit(fx["portfolio"]["id"], 100000)
        fetched = validate_success(api.get_cash_flow_event(event["id"], ADVISOR))
        assert_cash_flow_event(fetched)
        assert fetched["kind"] == "MANUAL_DEPOSIT"
        assert fetched["amount_cents"] == 100000
        assert fetched["balance_after_cents"] == 100000
        assert fetched["valuation_before_cents"] == 0
        assert fetched["source_type"] == "MANUAL"
        assert fetched["source_id"] is None

    def test_immediate_read_after_write_visibility(self, api):
        """PRD §2.9: "A portfolio's `cash_balance_cents` at any moment is the
        sum of `amount_cents` across its events, with immediate consistency
        after every append."
        PRD §2.9: "A position's `market_value_cents` is its `quantity`
        multiplied by the security's current `price_cents`."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        fx = setup_active_portfolio(targets=T_US_ONLY, client_name="Imm")
        p = fx["portfolio"]["id"]
        security = create_security("EQA", "US_EQUITY", 1000)
        position = validate_success(api.create_position(
            {"portfolio_id": p, "security_id": security["id"], "quantity": 10,
             "opening_cost_basis_cents": 7000}, ADVISOR), 201)
        assert position["market_value_cents"] == 10000, (
            "the create response itself carries computed fields")
        portfolio = validate_success(api.get_portfolio(p, ADVISOR))
        assert portfolio["total_value_cents"] == 10000
        repriced = validate_success(api.reprice_security(security["id"], 1200,
                                                         COMPLIANCE))
        assert repriced["price_cents"] == 1200
        rows, _ = validate_paginated(api.list_positions(
            ADVISOR, params={"portfolio_id": p, "security_id": security["id"]}))
        assert rows[0]["market_value_cents"] == 12000
        client = validate_success(api.get_client(fx["client"]["id"], ADVISOR))
        assert client["total_aum_cents"] == 12000


class TestListingAndPagination:
    def test_pagination_defaults_limits_and_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items and defaults to 0."
        PRD §2.2: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_limits_and_envelope
        """
        for i in range(1, 13):
            create_security(f"S{i:02d}", "US_EQUITY", 100)
        page1, meta1 = validate_paginated(api.list_securities(COMPLIANCE))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        body = api.list_securities(COMPLIANCE).json()
        assert body["response_type"] == "array"
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]
        page3, meta3 = validate_paginated(
            api.list_securities(COMPLIANCE, params={"limit": 2, "offset": 10}))
        assert len(page3) == 2
        assert meta3["has_more"] is False
        assert meta3["total_count"] == 12
        # limit 0 is below the minimum of 1.
        validate_error(api.list_securities(COMPLIANCE, params={"limit": 0}),
                       ApiErrorId.ERR_INVALID_REQUEST)

    def test_list_filters_combine_on_portfolios(self, api):
        """PRD §3.4: "Portfolios themselves list with filters on `client_id`,
        `lifecycle_status`, and `drift_status`."

        Design: Corner/endpoints/list_filters_combine_on_portfolios
        """
        c1 = create_active_client(full_name="F1", risk_tolerance_score=50)
        c2 = create_active_client(full_name="F2", risk_tolerance_score=50)
        get_success_data(api.create_portfolio(
            create_portfolio_payload(c1["id"], name="P1"), ADVISOR))
        get_success_data(api.create_portfolio(
            create_portfolio_payload(c1["id"], name="P2",
                                     tax_status="TAX_DEFERRED"), ADVISOR))
        get_success_data(api.create_portfolio(
            create_portfolio_payload(c2["id"], name="P3",
                                     tax_status="TAX_EXEMPT"), ADVISOR))
        rows1, _ = validate_paginated(
            api.list_portfolios(ADVISOR, params={"client_id": c1["id"]}))
        assert len(rows1) == 2, "no leakage of the other client's portfolio"
        rows2, _ = validate_paginated(api.list_portfolios(
            ADVISOR, params={"client_id": c1["id"], "lifecycle_status": "OPEN"}))
        assert len(rows2) == 2
        rows3, meta3 = validate_paginated(api.list_portfolios(
            ADVISOR, params={"client_id": c1["id"], "lifecycle_status": "FROZEN"}))
        assert rows3 == [] and meta3["total_count"] == 0

    def test_fk_reverse_reachability_filtered_lists(self, api):
        """PRD §3.2: "IPS records may be listed with filters on `client_id`,
        `benchmark_id`, `supersedes_ips_id`, and `status`"
        PRD §3.4: "Positions list with filters on `portfolio_id` and
        `security_id`."
        PRD §3.4: "The ledger is readable through the cash-flow event list,
        filterable by `portfolio_id`, by `kind`, and by an `occurred_at`
        window bounded by `from` and `to`"

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        c1 = create_active_client(full_name="FK1", risk_tolerance_score=50)
        bench = create_benchmark(name="Bench")
        ips = create_active_ips(c1, bench, targets=[
            {"asset_class": "US_EQUITY", "target_pct": 100.00, "band_pct": 50.00},
        ])
        p = get_success_data(api.create_portfolio(
            create_portfolio_payload(c1["id"], name="P"), ADVISOR))
        get_success_data(api.activate_portfolio(p["id"], ADVISOR))
        deposit(p["id"], 5000)
        security = create_security("EQA", "US_EQUITY", 1000)
        add_position(p["id"], security["id"], 5, 5000)
        c2 = create_active_client(full_name="FK2", risk_tolerance_score=50)
        q = get_success_data(api.create_portfolio(
            create_portfolio_payload(c2["id"], name="Q"), ADVISOR))
        rows1, _ = validate_paginated(
            api.list_ips(ADVISOR, params={"client_id": c1["id"]}))
        assert len(rows1) == 1 and rows1[0]["id"] == ips["id"]
        rows2, _ = validate_paginated(
            api.list_positions(ADVISOR, params={"portfolio_id": p["id"]}))
        assert len(rows2) == 1
        rows3, _ = validate_paginated(
            api.list_cash_flow_events(ADVISOR, params={"portfolio_id": p["id"]}))
        assert len(rows3) == 1
        # Foreign filters return empty arrays — no cross-client leakage.
        rows4, _ = validate_paginated(
            api.list_ips(ADVISOR, params={"client_id": c2["id"]}))
        assert rows4 == []
        rows5, _ = validate_paginated(
            api.list_positions(ADVISOR, params={"portfolio_id": q["id"]}))
        assert rows5 == []
