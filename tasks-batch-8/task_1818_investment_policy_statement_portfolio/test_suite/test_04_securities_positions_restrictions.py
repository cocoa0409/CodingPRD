"""Security catalog, restricted list, positions, and the reprice cascade (PRD §3.3, §3.4)."""
from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    ApiErrorId,
    add_position,
    create_active_client,
    create_benchmark,
    create_position_payload,
    create_restricted_list_entry_payload,
    create_security,
    create_security_payload,
    create_withdrawal,
    get_success_data,
    model_withdrawal,
    set_clock,
    setup_active_portfolio,
    setup_three_lot_portfolio,
    validate_error,
    validate_paginated,
    validate_success,
)

T_CASH = [
    {"asset_class": "CASH_EQUIVALENT", "target_pct": 100.00, "band_pct": 50.00},
]
T_US_ONLY = [
    {"asset_class": "US_EQUITY", "target_pct": 100.00, "band_pct": 50.00},
]


class TestSecurityCreation:
    def test_security_ticker_must_be_uppercase(self, api):
        """PRD §3.3: "A `ComplianceOfficer` registers a security with an
        uppercase `ticker` (letters, digits, and dots; unique by exact match —
        a duplicate is rejected as `ERR_INVALID_REQUEST`), its `asset_class`
        from the same five-class enum used by allocation targets, and an
        `initial_price_cents` of at least 1."

        Design: Corner/entities/security_ticker_must_be_uppercase
        """
        validate_error(
            api.create_security(create_security_payload(
                ticker="eqa", asset_class="US_EQUITY", initial_price_cents=1000),
                COMPLIANCE),
            ApiErrorId.ERR_INVALID_REQUEST)
        security = validate_success(api.create_security(
            create_security_payload(ticker="EQA", asset_class="US_EQUITY",
                                    initial_price_cents=1000), COMPLIANCE), 201)
        assert security["ticker"] == "EQA"
        assert security["trading_status"] == "LISTED"
        assert security["price_cents"] == 1000

    def test_security_trading_status_machine_and_referential_guards(self, api):
        """PRD §3.3: "Trading status moves `LISTED → HALTED` and back
        `HALTED → LISTED` freely under compliance control, and
        `LISTED → DELISTED` or `HALTED → DELISTED` only when no position
        anywhere holds more than zero units of the security, else
        `ERR_SECURITY_IN_USE`."
        PRD §3.4: "The security must be `LISTED`, else
        `ERR_SECURITY_NOT_TRADEABLE`"

        Design: Corner/state_machines/security_trading_status_machine_and_referential_guards
        """
        fx = setup_active_portfolio(targets=T_US_ONLY)
        p = fx["portfolio"]["id"]
        s1 = create_security("SEC1", "US_EQUITY", 1000)
        s2 = create_security("SEC2", "US_EQUITY", 1000)
        # HALTED blocks transfer-in.
        get_success_data(api.set_trading_status(s1["id"], "HALTED", COMPLIANCE))
        validate_error(
            api.create_position(create_position_payload(
                p, s1["id"], quantity=5, opening_cost_basis_cents=5000), ADVISOR),
            ApiErrorId.ERR_SECURITY_NOT_TRADEABLE)
        # Resuming restores intake.
        get_success_data(api.set_trading_status(s1["id"], "LISTED", COMPLIANCE))
        get_success_data(api.create_position(create_position_payload(
            p, s1["id"], quantity=5, opening_cost_basis_cents=5000), ADVISOR))
        # Delist of a held security is refused.
        get_success_data(api.set_trading_status(s1["id"], "HALTED", COMPLIANCE))
        validate_error(api.set_trading_status(s1["id"], "DELISTED", COMPLIANCE),
                       ApiErrorId.ERR_SECURITY_IN_USE)
        # Delist of an unheld security succeeds; DELISTED is terminal.
        s2 = get_success_data(api.set_trading_status(s2["id"], "DELISTED", COMPLIANCE))
        assert s2["trading_status"] == "DELISTED"
        validate_error(api.set_trading_status(s2["id"], "LISTED", COMPLIANCE),
                       ApiErrorId.ERR_SECURITY_INVALID_STATE)


class TestRestrictedList:
    def test_restricted_entry_status_derived_from_clock(self, api):
        """PRD §3.3: "An entry's `status` is never stored; it derives from the
        logical clock as `SCHEDULED` when the clock is earlier than
        `effective_from`, `ACTIVE` when the clock is at or after
        `effective_from` and before `effective_to`, and `EXPIRED` at or after
        `effective_to`."

        Design: Corner/entities/restricted_entry_status_derived_from_clock
        """
        security = create_security("EQR", "US_EQUITY", 1000)
        entry = get_success_data(api.create_restricted_list_entry(
            create_restricted_list_entry_payload(
                security["id"],
                restriction_level="NO_TRADE",
                effective_from="2026-08-05T00:00:00Z",
                effective_to="2026-08-10T00:00:00Z"), COMPLIANCE))
        # Default clock 2026-08-01T00:00:00Z: before the window.
        assert validate_success(
            api.get_restricted_list_entry(entry["id"], COMPLIANCE))["status"] == (
                "SCHEDULED")
        # From is inclusive.
        set_clock("2026-08-05T00:00:00Z")
        assert validate_success(
            api.get_restricted_list_entry(entry["id"], COMPLIANCE))["status"] == "ACTIVE"
        # To is exclusive.
        set_clock("2026-08-10T00:00:00Z")
        assert validate_success(
            api.get_restricted_list_entry(entry["id"], COMPLIANCE))["status"] == (
                "EXPIRED")

    def test_restriction_windows_adjacency_allowed(self, api):
        """PRD §3.3: "Windows for the same security observe half-open
        semantics — two entries whose intervals overlap at all are rejected
        with `ERR_RESTRICTION_WINDOW_OVERLAP`, while mere adjacency, where one
        entry's `effective_to` equals the next entry's `effective_from`, is
        permitted."

        Design: Difficulty/resource_temporal_overlap/restriction_windows_half_open_adjacency_allowed
        """
        security = create_security("EQR", "US_EQUITY", 1000)
        # A [08-10, 08-20)
        entry_a = validate_success(api.create_restricted_list_entry(
            create_restricted_list_entry_payload(
                security["id"], restriction_level="NO_BUY",
                effective_from="2026-08-10T00:00:00Z",
                effective_to="2026-08-20T00:00:00Z"), COMPLIANCE), 201)
        # B [08-20, 08-25): B.effective_from == A.effective_to — adjacency.
        entry_b = validate_success(api.create_restricted_list_entry(
            create_restricted_list_entry_payload(
                security["id"], restriction_level="NO_TRADE",
                effective_from="2026-08-20T00:00:00Z",
                effective_to="2026-08-25T00:00:00Z"), COMPLIANCE), 201)
        assert entry_b["effective_from"] == entry_a["effective_to"]
        # D [08-09, 08-10): adjacency on the other side also allowed.
        validate_success(api.create_restricted_list_entry(
            create_restricted_list_entry_payload(
                security["id"], restriction_level="NO_TRADE",
                effective_from="2026-08-09T00:00:00Z",
                effective_to="2026-08-10T00:00:00Z"), COMPLIANCE), 201)

    def test_restriction_windows_overlap_rejected(self, api):
        """PRD §3.3: "two entries whose intervals overlap at all are rejected
        with `ERR_RESTRICTION_WINDOW_OVERLAP`" — and the rule applies
        regardless of `restriction_level` on either side.

        Design: Difficulty/resource_temporal_overlap/restriction_windows_half_open_adjacency_allowed
        """
        security = create_security("EQR", "US_EQUITY", 1000)
        validate_success(api.create_restricted_list_entry(
            create_restricted_list_entry_payload(
                security["id"], restriction_level="NO_BUY",
                effective_from="2026-08-10T00:00:00Z",
                effective_to="2026-08-20T00:00:00Z"), COMPLIANCE), 201)
        validate_success(api.create_restricted_list_entry(
            create_restricted_list_entry_payload(
                security["id"], restriction_level="NO_TRADE",
                effective_from="2026-08-20T00:00:00Z",
                effective_to="2026-08-25T00:00:00Z"), COMPLIANCE), 201)
        # C [08-19, 08-21) overlaps both A and B.
        validate_error(
            api.create_restricted_list_entry(
                create_restricted_list_entry_payload(
                    security["id"], restriction_level="NO_BUY",
                    effective_from="2026-08-19T00:00:00Z",
                    effective_to="2026-08-21T00:00:00Z"), COMPLIANCE),
            ApiErrorId.ERR_RESTRICTION_WINDOW_OVERLAP)

    def test_date_range_validation_across_three_endpoints(self, api):
        """PRD §3.3: "The window must be non-degenerate: a start not strictly
        earlier than the end is rejected with `ERR_INVALID_DATE_RANGE`."
        PRD §3.7: "a `period_start` and `period_end` as `YYYY-MM-DD` dates
        forming a closed interval — both bounds inclusive, and a start later
        than the end is rejected with `ERR_INVALID_DATE_RANGE`"
        PRD §3.3: "terminating an entry that is already `EXPIRED` is rejected
        with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/date_range_validation_across_three_endpoints
        """
        security = create_security("EQR", "US_EQUITY", 1000)
        expired = get_success_data(api.create_restricted_list_entry(
            create_restricted_list_entry_payload(
                security["id"], restriction_level="NO_BUY",
                effective_from="2026-07-01T00:00:00Z",
                effective_to="2026-07-31T00:00:00Z"), COMPLIANCE))
        client = create_active_client(full_name="DR", risk_tolerance_score=50)
        portfolio = get_success_data(api.create_portfolio(
            {"client_id": client["id"], "name": "P", "tax_status": "TAX_EXEMPT"},
            ADVISOR))
        bench = create_benchmark(name="Bench")
        # Empty half-open window (from == to).
        validate_error(
            api.create_restricted_list_entry(
                create_restricted_list_entry_payload(
                    security["id"], restriction_level="NO_BUY",
                    effective_from="2026-09-10T00:00:00Z",
                    effective_to="2026-09-10T00:00:00Z"), COMPLIANCE),
            ApiErrorId.ERR_INVALID_DATE_RANGE)
        # Report with period_start > period_end.
        validate_error(
            api.create_performance_report(
                {"portfolio_id": portfolio["id"], "benchmark_id": bench["id"],
                 "period_start": "2026-08-31", "period_end": "2026-08-01",
                 "calculation_method": "TIME_WEIGHTED", "beginning_value_cents": 0,
                 "ending_value_cents": 0, "benchmark_return_bps": 0}, ADVISOR),
            ApiErrorId.ERR_INVALID_DATE_RANGE)
        # Terminate an already-EXPIRED entry.
        validate_error(api.terminate_restricted_list_entry(expired["id"], COMPLIANCE),
                       ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestPositionCreation:
    def test_position_create_rejects_computed_field_injection(self, api):
        """PRD §2.7: "unknown request fields — all rejected as
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/position_computed_fields_at_create_and_injection_rejected
        """
        fx = setup_active_portfolio(targets=T_US_ONLY)
        security = create_security("EQA", "US_EQUITY", 1000)
        payload = create_position_payload(fx["portfolio"]["id"], security["id"],
                                          quantity=10, opening_cost_basis_cents=7000)
        payload["market_value_cents"] = 1
        validate_error(api.create_position(payload, ADVISOR),
                       ApiErrorId.ERR_INVALID_REQUEST)

    def test_position_computed_fields_at_create(self, api):
        """PRD §3.4: "On creation the position's `market_value_cents` is
        computed as `quantity` times the security's current `price_cents`,
        `unrealized_gain_cents` as `market_value_cents` minus
        `cost_basis_cents`"

        Design: Corner/entities/position_computed_fields_at_create_and_injection_rejected
        """
        fx = setup_active_portfolio(targets=T_US_ONLY)
        security = create_security("EQA", "US_EQUITY", 1000)
        position = validate_success(api.create_position(
            create_position_payload(fx["portfolio"]["id"], security["id"], quantity=10,
                                    opening_cost_basis_cents=7000), ADVISOR), 201)
        assert position["market_value_cents"] == 10000, "10 x 1000"
        assert position["unrealized_gain_cents"] == 3000
        assert position["cost_basis_cents"] == 7000

    def test_duplicate_position_pair_rejected(self, api):
        """PRD §3.4: "One position exists per security per portfolio: a second
        transfer-in for the same `(portfolio_id, security_id)` pair is rejected
        with `ERR_POSITION_EXISTS`."

        Design: Corner/validations/duplicate_position_pair_rejected
        """
        fx = setup_active_portfolio(targets=T_US_ONLY)
        security = create_security("EQA", "US_EQUITY", 1000)
        add_position(fx["portfolio"]["id"], security["id"], 5, 5000)
        validate_error(
            api.create_position(create_position_payload(
                fx["portfolio"]["id"], security["id"], quantity=1,
                opening_cost_basis_cents=1000), ADVISOR),
            ApiErrorId.ERR_POSITION_EXISTS)
        # Existing position unchanged.
        rows, _ = validate_paginated(api.list_positions(
            ADVISOR, params={"portfolio_id": fx["portfolio"]["id"],
                             "security_id": security["id"]}))
        assert len(rows) == 1
        assert rows[0]["quantity"] == 5
        assert rows[0]["cost_basis_cents"] == 5000


class TestRepriceCascade:
    def _setup_modeled_fixture(self, api):
        fx = setup_three_lot_portfolio()
        w = create_withdrawal(fx["portfolio"]["id"], 150000, "TAX_AWARE")
        model_withdrawal(w["id"])
        return fx, w

    def test_reprice_recomputes_valuation_and_drift(self, api):
        """PRD §3.3: "The security's `price_cents` updates; every position
        holding the security recomputes its `market_value_cents` and
        `unrealized_gain_cents` (each such position's `version` increments);
        every affected portfolio recomputes `total_value_cents` and re-runs
        the drift assessment (each such portfolio's `version` increments)"

        Design: Difficulty/transitive_cascade/reprice_cascade_through_valuation_drift_and_model_staleness
        """
        fx, _w = self._setup_modeled_fixture(api)
        lot1 = fx["positions"]["LOT1"]
        # Before: US 50% vs 60% target -> BREACHED.
        before = validate_success(api.get_portfolio(fx["portfolio"]["id"], ADVISOR))
        assert before["drift_status"] == "BREACHED"
        assert before["total_value_cents"] == 400000
        # Hop 1-2: reprice EQA 1000 -> 1600 ripples position -> portfolio.
        get_success_data(api.reprice_security(fx["securities"]["EQA"]["id"], 1600,
                                              COMPLIANCE))
        pos = validate_success(api.get_position(lot1["id"], ADVISOR))
        assert pos["market_value_cents"] == 160000
        assert pos["unrealized_gain_cents"] == 70000
        portfolio = validate_success(api.get_portfolio(fx["portfolio"]["id"], ADVISOR))
        assert portfolio["total_value_cents"] == 460000
        # Hop 3: US 5652bps vs 6000 target — drift 348 within the 500 band.
        assert portfolio["drift_status"] == "WITHIN_BANDS"

    def test_reprice_reverts_modeled_withdrawal(self, api):
        """PRD §3.3: "every withdrawal request of an affected portfolio that
        had been modeled reverts from `MODELED` to `SUBMITTED` with its modeled
        fields cleared, since the model was priced at stale quotes."

        Design: Difficulty/transitive_cascade/reprice_cascade_through_valuation_drift_and_model_staleness
        """
        fx, w = self._setup_modeled_fixture(api)
        modeled = validate_success(api.get_withdrawal_request(w["id"], ADVISOR))
        assert modeled["status"] == "MODELED"
        # Hop 4: the reprice reverts the stale model.
        get_success_data(api.reprice_security(fx["securities"]["EQA"]["id"], 1600,
                                              COMPLIANCE))
        reverted = validate_success(api.get_withdrawal_request(w["id"], ADVISOR))
        assert reverted["status"] == "SUBMITTED"
        # §3.6 pins `modeled_at` as "null until the request reaches MODELED";
        # the null/empty rendering of the other cleared fields is not pinned.
        assert reverted["modeled_at"] is None
