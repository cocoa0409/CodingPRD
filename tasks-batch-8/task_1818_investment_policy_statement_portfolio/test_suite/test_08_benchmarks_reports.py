"""Benchmarks and performance measurement (PRD §3.7)."""
from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    ApiErrorId,
    add_position,
    create_active_client,
    create_active_ips,
    create_benchmark,
    create_benchmark_payload,
    create_performance_report_payload,
    create_portfolio_payload,
    create_security,
    deposit,
    get_success_data,
    reprice,
    set_clock,
    setup_active_portfolio,
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


class TestBenchmarks:
    def test_benchmark_unique_name_and_default_description(self, api):
        """PRD §3.7: "A `ComplianceOfficer` creates a benchmark with a `name`
        that is unique by exact match (duplicates are rejected as
        `ERR_INVALID_REQUEST`) and an optional `description` that defaults to
        empty; the benchmark begins `ACTIVE`."

        Design: Corner/entities/benchmark_unique_name_and_default_description
        """
        # The factory injects a non-empty description by default; this test
        # exercises the omission path, so the key must be absent entirely.
        omitted = create_benchmark_payload(name="Core Blend")
        omitted.pop("description", None)
        first = validate_success(api.create_benchmark(omitted, COMPLIANCE), 201)
        assert first["status"] == "ACTIVE"
        validate_error(
            api.create_benchmark(create_benchmark_payload(name="Core Blend"),
                                 COMPLIANCE),
            ApiErrorId.ERR_INVALID_REQUEST)
        rows, _ = validate_paginated(
            api.list_benchmarks(COMPLIANCE, params={"status": "ACTIVE"}))
        assert len(rows) == 1
        assert rows[0]["description"] == "", "omitted description defaults to empty"

    def test_benchmark_retire_guards(self, api):
        """PRD §3.7: "Retirement moves `ACTIVE → RETIRED` and is refused while
        any IPS in `ACTIVE` status references the benchmark, surfacing
        `ERR_BENCHMARK_IN_USE`; retiring a benchmark that is not `ACTIVE`
        surfaces `ERR_BENCHMARK_INVALID_STATE`. `RETIRED` is terminal."

        Design: Corner/state_machines/benchmark_retire_guards
        """
        client = create_active_client(full_name="BmG", risk_tolerance_score=50)
        in_use = create_benchmark(name="InUse")
        free = create_benchmark(name="Free")
        create_active_ips(client, in_use, targets=T_CASH)
        validate_error(api.retire_benchmark(in_use["id"], COMPLIANCE),
                       ApiErrorId.ERR_BENCHMARK_IN_USE)
        retired = validate_success(api.retire_benchmark(free["id"], COMPLIANCE))
        assert retired["status"] == "RETIRED"
        validate_error(api.retire_benchmark(free["id"], COMPLIANCE),
                       ApiErrorId.ERR_BENCHMARK_INVALID_STATE)


class TestReturnVariants:
    def _setup_perf_fixture(self, api):
        """P4: E1 +1000000 @08-01; 100 EQX @1000 basis 100000; reprice 1200;
        E2 +200000 @08-11; reprice 1500; E3 -100000 @08-21.
        P4b (same client, cash-only): +1000000 @08-01, +200000 @08-11,
        -100000 @08-21."""
        # §3.4 rejects occurred_at later than the logical clock: advance the
        # clock past the latest flow date before recording backdated flows.
        set_clock("2026-08-21T00:00:00Z")
        fx = setup_active_portfolio(targets=T_US_ONLY, tax_status="TAX_EXEMPT",
                                    client_name="Perf Client")
        p4 = fx["portfolio"]["id"]
        deposit(p4, 1000000, "2026-08-01T00:00:00Z")
        eqx = create_security("EQX", "US_EQUITY", 1000)
        add_position(p4, eqx["id"], 100, 100000)
        reprice(eqx["id"], 1200)
        e2 = deposit(p4, 200000, "2026-08-11T00:00:00Z")
        reprice(eqx["id"], 1500)
        e3 = withdraw_cash(p4, 100000, "2026-08-21T00:00:00Z")
        # Cash-only sibling portfolio for the MONEY_WEIGHTED twin.
        p4b = get_success_data(api.create_portfolio(
            create_portfolio_payload(fx["client"]["id"], name="P4b",
                                     tax_status="TAX_EXEMPT"), ADVISOR))
        get_success_data(api.activate_portfolio(p4b["id"], ADVISOR))
        deposit(p4b["id"], 1000000, "2026-08-01T00:00:00Z")
        deposit(p4b["id"], 200000, "2026-08-11T00:00:00Z")
        withdraw_cash(p4b["id"], 100000, "2026-08-21T00:00:00Z")
        fx.update({"p4b": p4b["id"], "e2": e2, "e3": e3})
        return fx

    def test_time_weighted_return_chains_around_flows(self, api):
        """PRD §3.7: "The product of every sub-period factor and the terminal
        factor, minus one, times 10,000, is rounded half-up once at the very
        end to an integer basis-point return; intermediate factors are never
        rounded."
        Here: (1120000/1100000) x (1350000/1320000) x (1250000/1250000) - 1
        -> 413 bps; excess over the 300bps benchmark is 113.

        Design: Difficulty/dual_variant_calc/performance_twr_vs_dietz_divergence
        """
        fx = self._setup_perf_fixture(api)
        p4 = fx["portfolio"]["id"]
        # The event snapshots pin the sub-period valuations.
        assert fx["e2"]["valuation_before_cents"] == 1120000
        assert fx["e3"]["valuation_before_cents"] == 1350000
        report = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                p4, fx["benchmark"]["id"], period_start="2026-08-01",
                period_end="2026-08-31", calculation_method="TIME_WEIGHTED",
                beginning_value_cents=1100000, ending_value_cents=1250000,
                benchmark_return_bps=300), ADVISOR))
        finalized = validate_success(
            api.finalize_performance_report(report["id"], COMPLIANCE))
        assert finalized["portfolio_return_bps"] == 413
        assert finalized["excess_return_bps"] == 113, "413 - 300"

    def test_money_weighted_dietz_diverges_from_twr(self, api):
        """PRD §3.7: "when the denominator is zero the return is zero basis
        points, otherwise the ratio times 10,000 is rounded half-up once to
        integer basis points."
        PRD §3.7: "Given mid-period flows, the two methods deliberately yield
        different returns from identical inputs."
        Here: 50000 / (1100000 + (2/3)*200000 - (1/3)*100000) -> 417 bps;
        excess 117 — a different answer than TIME_WEIGHTED's 413.

        Design: Difficulty/dual_variant_calc/performance_twr_vs_dietz_divergence
        """
        fx = self._setup_perf_fixture(api)
        report = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                fx["p4b"], fx["benchmark"]["id"], period_start="2026-08-01",
                period_end="2026-08-31", calculation_method="MONEY_WEIGHTED",
                beginning_value_cents=1100000, ending_value_cents=1250000,
                benchmark_return_bps=300), ADVISOR))
        finalized = validate_success(
            api.finalize_performance_report(report["id"], COMPLIANCE))
        assert finalized["portfolio_return_bps"] == 417
        assert finalized["excess_return_bps"] == 117
        assert finalized["portfolio_return_bps"] != 413

    def test_performance_flow_window_excludes_period_start_date(self, api):
        """PRD §3.7: "Both methods draw their flows from the portfolio's ledger
        over a consistent window: events whose `occurred_at` UTC date is
        strictly after `period_start` and on or before `period_end` — the start
        date is exclusive, the end date inclusive"
        The deposit dated exactly 2026-08-01 is excluded; including it would
        zero a sub-period and report -10000 bps instead of 0.

        Design: Corner/calculations/performance_flow_window_excludes_period_start_date
        """
        # §3.4 rejects future-dated occurred_at; advance the clock so the
        # 08-05 deposit is not later than the logical clock.
        set_clock("2026-08-10T00:00:00Z")
        fx = setup_active_portfolio(targets=T_CASH, tax_status="TAX_EXEMPT",
                                    client_name="Win")
        p = fx["portfolio"]["id"]
        deposit(p, 500000, "2026-08-01T00:00:00Z")
        deposit(p, 100000, "2026-08-05T00:00:00Z")
        report = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                p, fx["benchmark"]["id"], period_start="2026-08-01",
                period_end="2026-08-10", calculation_method="TIME_WEIGHTED",
                beginning_value_cents=500000, ending_value_cents=600000,
                benchmark_return_bps=25), ADVISOR))
        finalized = validate_success(
            api.finalize_performance_report(report["id"], COMPLIANCE))
        assert finalized["portfolio_return_bps"] == 0, (
            "only the 08-05 deposit is inside (2026-08-01, 2026-08-10]")
        assert finalized["excess_return_bps"] == -25


class TestFinalizeGates:
    def test_finalize_rejected_when_benchmark_retired(self, api):
        """PRD §3.7: "the referenced benchmark must be `ACTIVE`, else
        `ERR_BENCHMARK_NOT_ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/report_finalize_gated_by_benchmark_active
        """
        client = create_active_client(full_name="Report Client",
                                      risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="Rep",
                                     tax_status="TAX_EXEMPT"), ADVISOR))
        b2 = create_benchmark(name="Retiring Bench", description="old")
        get_success_data(api.retire_benchmark(b2["id"], COMPLIANCE))
        r2 = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                portfolio["id"], b2["id"], period_start="2026-08-01",
                period_end="2026-08-31", beginning_value_cents=100000,
                ending_value_cents=110000, benchmark_return_bps=0), ADVISOR))
        validate_error(api.finalize_performance_report(r2["id"], COMPLIANCE),
                       ApiErrorId.ERR_BENCHMARK_NOT_ACTIVE)

    def test_finalize_succeeds_while_benchmark_active(self, api):
        """PRD §3.7: "Finalization computes `portfolio_return_bps` by the
        report's chosen method and derives `excess_return_bps` as
        `portfolio_return_bps` minus `benchmark_return_bps`."

        Design: Difficulty/cross_entity_state_dependency/report_finalize_gated_by_benchmark_active
        """
        client = create_active_client(full_name="Report Client",
                                      risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="Rep",
                                     tax_status="TAX_EXEMPT"), ADVISOR))
        b2 = create_benchmark(name="Retiring Bench", description="old")
        b3 = create_benchmark(name="Live Bench", description="current")
        get_success_data(api.retire_benchmark(b2["id"], COMPLIANCE))
        r2 = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                portfolio["id"], b2["id"], period_start="2026-08-01",
                period_end="2026-08-31", beginning_value_cents=100000,
                ending_value_cents=110000, benchmark_return_bps=0), ADVISOR))
        r3 = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                portfolio["id"], b3["id"], period_start="2026-09-01",
                period_end="2026-09-30", beginning_value_cents=110000,
                ending_value_cents=110000, benchmark_return_bps=0), ADVISOR))
        validate_error(api.finalize_performance_report(r2["id"], COMPLIANCE),
                       ApiErrorId.ERR_BENCHMARK_NOT_ACTIVE)
        finalized = validate_success(
            api.finalize_performance_report(r3["id"], COMPLIANCE))
        assert finalized["status"] == "FINALIZED"
        assert finalized["portfolio_return_bps"] == 0
        assert finalized["excess_return_bps"] == 0
        # The rejected finalize left its report in DRAFT.
        assert validate_success(
            api.get_performance_report(r2["id"], ADVISOR))["status"] == "DRAFT"

    def test_report_periods_touching_boundary_rejected(self, api):
        """PRD §3.7: "the closed period may not touch any already-`FINALIZED`
        report of the same portfolio — closed-interval semantics mean a shared
        boundary date already counts as overlap, and an offending report is
        rejected with `ERR_REPORT_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_touching_rejected
        """
        fx = self._three_reports(api)
        r1, r2, _r3 = fx
        finalized1 = validate_success(
            api.finalize_performance_report(r1["id"], COMPLIANCE))
        assert finalized1["portfolio_return_bps"] == 1000, "110000/100000 - 1"
        # [08-31, 09-30] shares the boundary date 2026-08-31 with R1.
        validate_error(api.finalize_performance_report(r2["id"], COMPLIANCE),
                       ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

    def test_report_periods_one_day_gap_accepted(self, api):
        """PRD §3.7: "closed-interval semantics mean a shared boundary date
        already counts as overlap" — a gap of at least one day leaves the
        periods disjoint.

        Design: Difficulty/resource_temporal_overlap/report_periods_closed_interval_touching_rejected
        """
        r1, r2, r3 = self._three_reports(api)
        get_success_data(api.finalize_performance_report(r1["id"], COMPLIANCE))
        validate_error(api.finalize_performance_report(r2["id"], COMPLIANCE),
                       ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)
        finalized3 = validate_success(
            api.finalize_performance_report(r3["id"], COMPLIANCE))
        assert finalized3["status"] == "FINALIZED"
        # The failed finalize left R2 unchanged.
        assert validate_success(
            api.get_performance_report(r2["id"], ADVISOR))["status"] == "DRAFT"

    def _three_reports(self, api):
        client = create_active_client(full_name="Periods Client",
                                      risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="Rep",
                                     tax_status="TAX_EXEMPT"), ADVISOR))
        bench = create_benchmark(name="Bench")
        r1 = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                portfolio["id"], bench["id"], period_start="2026-08-01",
                period_end="2026-08-31", beginning_value_cents=100000,
                ending_value_cents=110000, benchmark_return_bps=0), ADVISOR))
        r2 = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                portfolio["id"], bench["id"], period_start="2026-08-31",
                period_end="2026-09-30", beginning_value_cents=110000,
                ending_value_cents=110000, benchmark_return_bps=0), ADVISOR))
        r3 = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                portfolio["id"], bench["id"], period_start="2026-09-01",
                period_end="2026-09-30", beginning_value_cents=110000,
                ending_value_cents=110000, benchmark_return_bps=0), ADVISOR))
        return r1, r2, r3

    def test_report_finalize_terminal_lockdown(self, api):
        """PRD §3.7: "The report must be `DRAFT`, else
        `ERR_REPORT_INVALID_STATE`" — `FINALIZED` is terminal.

        Design: Corner/state_machines/report_finalize_terminal_lockdown
        """
        client = create_active_client(full_name="RepL", risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            create_portfolio_payload(client["id"], name="P",
                                     tax_status="TAX_EXEMPT"), ADVISOR))
        bench = create_benchmark(name="Bench")
        report = get_success_data(api.create_performance_report(
            create_performance_report_payload(
                portfolio["id"], bench["id"], period_start="2026-08-01",
                period_end="2026-08-31", beginning_value_cents=100000,
                ending_value_cents=100000, benchmark_return_bps=50), ADVISOR))
        finalized = validate_success(
            api.finalize_performance_report(report["id"], COMPLIANCE))
        assert finalized["portfolio_return_bps"] == 0
        assert finalized["excess_return_bps"] == -50, "0 - 50"
        validate_error(api.finalize_performance_report(report["id"], COMPLIANCE),
                       ApiErrorId.ERR_REPORT_INVALID_STATE)
        reread = validate_success(api.get_performance_report(report["id"], ADVISOR))
        assert reread["portfolio_return_bps"] == 0
        assert reread["excess_return_bps"] == -50
