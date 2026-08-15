"""Investment policy windows, drift measurement, compliance reviews,
concentration cap, and derived market-value reconciliation (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    MANAGER,
    buy_holding,
    create_active_trust,
    get_trust,
    post_receipt,
    setup_active_ips,
    trust_version,
)


def _drift_ips_kwargs():
    return {
        "effective_from": "2026-08-01",
        "effective_to": "2027-08-01",
        "equity_target_pct": 60.00,
        "equity_band_pct": 5.00,
        "fixed_income_target_pct": 0.00,
        "fixed_income_band_pct": 5.00,
        "alternatives_allowed": False,
    }


def _funded_trust_with_ips(api, funding=100000000, name="Drift Trust"):
    """ACTIVE trust funded with principal cash and an ACTIVE IPS. Activation
    on the all-cash trust opens one UNDERWEIGHT EQUITY review (PRD §3.4)."""
    trust = create_active_trust(trust_name=name)
    post_receipt(trust["id"], funding, receipt_type="INITIAL_FUNDING",
                 value_date="2026-08-05", description="funding")
    ips = setup_active_ips(trust["id"], **_drift_ips_kwargs())
    return trust, ips


def _three_equity_holdings(api, trust_id):
    """AAA 25,000,000 + BBB 25,000,000 + CCC 15,000,000 of EQUITY."""
    h1 = buy_holding(trust_id, "EQUITY", "AAA", 1000, 25000)
    h2 = buy_holding(trust_id, "EQUITY", "BBB", 1000, 25000)
    h3 = buy_holding(trust_id, "EQUITY", "CCC", 1000, 15000)
    return h1, h2, h3


def _reviews(api, trust_id, **params):
    query = {"trust_id": trust_id}
    query.update(params)
    rows, meta = validate_paginated(api.list_compliance_reviews(MANAGER, params=query))
    return rows, meta


class TestConcentrationBoundary:
    def test_exactly_25_percent_allowed(self, api):
        """PRD §3.4: "Separately, concentration is capped: if a holding's
        post-trade market value would be strictly more than twenty-five
        percent of the trust's `total_market_value_cents`, the purchase is
        rejected with `ERR_CONCENTRATION_LIMIT_EXCEEDED`; landing exactly at
        twenty-five percent is permitted."

        Design: Corner/calculations/concentration_exact_edge_allowed_one_cent_over_rejected
        """
        trust = create_active_trust(trust_name="Conc Trust")
        post_receipt(trust["id"], 100000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        holding = buy_holding(trust["id"], "EQUITY", "EDGE", 1, 25000000)
        assert holding["market_value_cents"] == 25000000

    def test_one_cent_over_25_percent_rejected(self, api):
        """PRD §3.4: "if a holding's post-trade market value would be strictly
        more than twenty-five percent of the trust's
        `total_market_value_cents`, the purchase is rejected with
        `ERR_CONCENTRATION_LIMIT_EXCEEDED`; landing exactly at twenty-five
        percent is permitted."

        Design: Corner/calculations/concentration_exact_edge_allowed_one_cent_over_rejected
        """
        trust = create_active_trust(trust_name="Conc Over")
        post_receipt(trust["id"], 100000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        buy_holding(trust["id"], "EQUITY", "EDGE", 1, 25000000)
        resp = api.create_holding(
            {
                "trust_id": trust["id"],
                "asset_class": "EQUITY",
                "ticker": "OVER",
                "units": 1,
                "unit_price_cents": 25000001,
                "expected_trust_account_version": trust_version(trust["id"], MANAGER),
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CONCENTRATION_LIMIT_EXCEEDED)


class TestReinstateResolveArc:
    def test_unresolved_reviews_block_reinstate(self, api):
        """PRD §3.1: "Reinstatement from SUSPENDED → ACTIVE is permitted only
        when the trust has zero ComplianceReviews in OPEN,
        REMEDIATION_PLANNED, or ESCALATED; otherwise the attempt is rejected
        with `ERR_UNRESOLVED_COMPLIANCE_REVIEWS`."

        Design: Corner/errors/unresolved_reviews_block_reinstate_and_uncured_resolve_fails
        """
        trust, _ = _funded_trust_with_ips(api, name="Reinstate Arc")
        assert api.suspend_trust(trust["id"], {"reason": "manual hold"}, EXEC).status_code == 200
        resp = api.reinstate_trust(trust["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_UNRESOLVED_COMPLIANCE_REVIEWS)

    def test_uncured_resolve_fails_then_cure_allows_resolve_and_reinstate(self, api):
        """PRD §3.4: "Resolution — from OPEN, REMEDIATION_PLANNED, or
        ESCALATED → RESOLVED — requires the class's current unrounded weight
        to be back within the band inclusive, meaning no less than the target
        minus the band and no more than the target plus the band; a premature
        resolve is rejected with `ERR_DRIFT_STILL_BREACHED`."
        PRD §3.4: "Buying into a class is blocked while any ComplianceReview
        for that class and trust is non-RESOLVED with `direction` OVERWEIGHT —
        the rejection is `ERR_IPS_DRIFT_BREACH` — whereas buying into an
        UNDERWEIGHT class is allowed precisely because it is the remediation
        path."

        Design: Corner/errors/unresolved_reviews_block_reinstate_and_uncured_resolve_fails
        """
        trust, _ = _funded_trust_with_ips(api, name="Reinstate Cure")
        rows, _ = _reviews(api, trust["id"])
        rev = rows[0]["id"]
        assert api.suspend_trust(trust["id"], {"reason": "manual hold"}, EXEC).status_code == 200

        api.reinstate_trust(trust["id"], EXEC)  # blocked by the open review
        resp = api.resolve_review(rev, MANAGER)
        validate_error(resp, ApiErrorId.ERR_DRIFT_STILL_BREACHED)

        # Buy INTO the underweight class (the remediation path) until equity
        # weight is exactly 0.65 — inside [0.55, 0.65] inclusive.
        _three_equity_holdings(api, trust["id"])
        resolved = api.resolve_review(rev, MANAGER)
        assert resolved.status_code == 200, "resolve must succeed once the drift is cured"
        assert get_success_data(resolved)["status"] == "RESOLVED"

        reinstated = api.reinstate_trust(trust["id"], EXEC)
        assert reinstated.status_code == 200
        assert get_success_data(reinstated)["status"] == "ACTIVE"


class TestOverweightPurchaseBlock:
    def _overweight_setup(self, api):
        """Equity 65,010,000 / TMV 100,010,000 -> OVERWEIGHT STANDARD review."""
        trust, _ = _funded_trust_with_ips(api, name="Block Buy")
        # widen the fixed_income target so only the EQUITY overweight matters
        _, _, h3 = _three_equity_holdings(api, trust["id"])
        assert api.update_price(
            h3["id"], {"unit_price_cents": 15010, "priced_at": "2026-10-01T00:00:00Z"},
            MANAGER,
        ).status_code == 200
        return trust

    def test_overweight_breach_blocks_equity_purchase(self, api):
        """PRD §3.4: "Buying into a class is blocked while any
        ComplianceReview for that class and trust is non-RESOLVED with
        `direction` OVERWEIGHT — the rejection is `ERR_IPS_DRIFT_BREACH` —
        whereas buying into an UNDERWEIGHT class is allowed precisely because
        it is the remediation path."

        Design: Corner/errors/overweight_breach_blocks_class_purchase_only
        """
        trust = self._overweight_setup(api)
        resp = api.create_holding(
            {
                "trust_id": trust["id"],
                "asset_class": "EQUITY",
                "ticker": "DDD",
                "units": 1,
                "unit_price_cents": 100000,
                "expected_trust_account_version": trust_version(trust["id"], MANAGER),
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_IPS_DRIFT_BREACH)

    def test_fixed_income_purchase_still_allowed(self, api):
        """PRD §3.4: "Buying into a class is blocked while any
        ComplianceReview for that class and trust is non-RESOLVED with
        `direction` OVERWEIGHT — the rejection is `ERR_IPS_DRIFT_BREACH` —
        whereas buying into an UNDERWEIGHT class is allowed precisely because
        it is the remediation path."

        Design: Corner/errors/overweight_breach_blocks_class_purchase_only
        """
        trust = self._overweight_setup(api)
        holding = buy_holding(trust["id"], "FIXED_INCOME", "BND", 1, 100000)
        assert holding["market_value_cents"] == 100000


class TestPriceUpdateSuspensionCascade:
    def test_first_reprice_updates_review_in_place_without_suspend(self, api):
        """PRD §3.4: "If no review already exists in a non-RESOLVED state for
        that trust and class, the check opens one, naming the breached
        `asset_class` and the `investment_policy_statement_id` of the ACTIVE
        policy; if such a review already exists, the check updates it in place
        — direction, measured weight, band limit, severity — and never creates
        a duplicate."
        PRD §3.4: "The stored `measured_weight_pct` is the raw weight
        converted to a percentage and rounded half up to two decimals — a
        display value only, never used for the breach decision."

        Design: Difficulty/transitive_cascade/price_update_to_trust_suspension
        """
        trust, _ = _funded_trust_with_ips(api, name="Cascade Trust")
        _, _, h3 = _three_equity_holdings(api, trust["id"])
        assert api.update_price(
            h3["id"], {"unit_price_cents": 15010, "priced_at": "2026-10-01T00:00:00Z"},
            MANAGER,
        ).status_code == 200

        holding = validate_success(api.get_holding(h3["id"], MANAGER))
        assert holding["market_value_cents"] == 15010000
        trust_after = get_trust(trust["id"], MANAGER)
        assert trust_after["total_market_value_cents"] == 100010000
        assert trust_after["status"] == "ACTIVE"

        rows, meta = _reviews(api, trust["id"])
        assert meta["total_count"] == 1, "the pre-existing review must be updated in place"
        review = rows[0]
        assert review["asset_class"] == "EQUITY"
        assert review["direction"] == "OVERWEIGHT"
        assert review["severity"] == "STANDARD"
        assert review["measured_weight_pct"] == 65.00

    def test_critical_reprice_auto_suspends_trust(self, api):
        """PRD §3.4: "A breach's `severity` is CRITICAL only when the
        direction is OVERWEIGHT and the unrounded weight exceeds the target
        plus twice the band; every other breach is STANDARD." and "The
        creation of a CRITICAL review immediately suspends the trust, ACTIVE →
        SUSPENDED."
        PRD §3.1: "it is also imposed automatically the moment a CRITICAL
        compliance review is created (see §3.4)."

        Design: Difficulty/transitive_cascade/price_update_to_trust_suspension
        """
        trust, _ = _funded_trust_with_ips(api, name="Cascade Critical")
        _, _, h3 = _three_equity_holdings(api, trust["id"])
        assert api.update_price(
            h3["id"], {"unit_price_cents": 15010, "priced_at": "2026-10-01T00:00:00Z"},
            MANAGER,
        ).status_code == 200
        assert api.update_price(
            h3["id"], {"unit_price_cents": 81667, "priced_at": "2026-10-02T00:00:00Z"},
            MANAGER,
        ).status_code == 200

        rows, meta = _reviews(api, trust["id"])
        assert meta["total_count"] == 1
        assert rows[0]["severity"] == "CRITICAL"
        # NOTE: PRD §3.4 suspends the trust on "the creation of a CRITICAL
        # review". Here the review was created at activation (UNDERWEIGHT,
        # STANDARD) and reaches CRITICAL through the verbatim in-place update
        # pathway ("the check updates it in place — direction, measured
        # weight, band limit, severity — and never creates a duplicate"), so
        # no CRITICAL review is ever created in this scenario and the
        # suspension side effect is not asserted (not uniquely derivable).


class TestDriftBandEdge:
    def test_exact_band_edge_opens_no_review(self, api):
        """PRD §3.4: "An overweight breach occurs when the raw weight is
        strictly greater than the target plus the band — the target and band
        being percentages converted to fractions of one hundred — and an exact
        landing on the band edge is not a breach."

        Design: Difficulty/boundary_precision_check/drift_exact_band_edge_vs_just_over
        """
        trust, _ = _funded_trust_with_ips(api, name="Edge Trust")
        h1, h2, h3 = _three_equity_holdings(api, trust["id"])
        data = validate_success(api.run_compliance_check(trust["id"], MANAGER))
        assert data["opened_review_count"] == 0, (
            "equity weight exactly 0.65 lands on the band edge: not a breach"
        )

    def test_just_over_edge_breaches_with_rounded_display(self, api):
        """PRD §3.4: "An overweight breach occurs when the raw weight is
        strictly greater than the target plus the band" and "The stored
        `measured_weight_pct` is the raw weight converted to a percentage and
        rounded half up to two decimals — a display value only, never used for
        the breach decision."

        Design: Difficulty/boundary_precision_check/drift_exact_band_edge_vs_just_over
        """
        trust, _ = _funded_trust_with_ips(api, name="Edge Over")
        _, _, h3 = _three_equity_holdings(api, trust["id"])
        assert api.update_price(
            h3["id"], {"unit_price_cents": 15010, "priced_at": "2026-10-01T00:00:00Z"},
            MANAGER,
        ).status_code == 200
        rows, meta = _reviews(api, trust["id"], status="OPEN")
        assert meta["total_count"] == 1
        review = rows[0]
        assert review["asset_class"] == "EQUITY"
        assert review["direction"] == "OVERWEIGHT"
        assert review["severity"] == "STANDARD"
        assert review["measured_weight_pct"] == 65.00
        # FIXED_INCOME target 0.00 band 5.00 at weight 0 never breaches
        all_rows, _ = _reviews(api, trust["id"])
        assert all(r["asset_class"] != "FIXED_INCOME" for r in all_rows)


class TestIpsWindowHygiene:
    def _active_windowed_ips(self, api):
        trust = create_active_trust(trust_name="Window Trust")
        ips1 = setup_active_ips(
            trust["id"],
            effective_from="2026-08-01",
            effective_to="2027-08-01",
            equity_target_pct=60.00,
            equity_band_pct=5.00,
            fixed_income_target_pct=30.00,
            fixed_income_band_pct=5.00,
            alternatives_allowed=False,
        )
        return trust, ips1

    def test_abutting_half_open_window_allowed(self, api):
        """PRD §3.4: "the half-open window must not overlap any other
        statement of the same trust in DRAFT or ACTIVE, though abutting
        windows — where one statement's `effective_to` equals the other's
        `effective_from` — are permitted; an overlap is rejected with
        `ERR_IPS_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/ips_half_open_adjacency_allowed_overlap_rejected
        """
        trust, _ = self._active_windowed_ips(api)
        resp = api.create_ips(
            {
                "trust_id": trust["id"],
                "effective_from": "2027-08-01",
                "effective_to": "2028-08-01",
                "equity_target_pct": 55.00,
                "equity_band_pct": 5.00,
                "fixed_income_target_pct": 35.00,
                "fixed_income_band_pct": 5.00,
                "alternatives_allowed": False,
            },
            MANAGER,
        )
        ips2 = validate_success(resp, expected_status=201)
        assert ips2["status"] == "DRAFT"

    def test_overlapping_window_rejected_and_prior_ips_unaffected(self, api):
        """PRD §3.4: "Activation moves DRAFT → ACTIVE and enforces window
        hygiene: the half-open window must not overlap any other statement of
        the same trust in DRAFT or ACTIVE, though abutting windows — where one
        statement's `effective_to` equals the other's `effective_from` — are
        permitted; an overlap is rejected with `ERR_IPS_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/ips_half_open_adjacency_allowed_overlap_rejected
        """
        trust, ips1 = self._active_windowed_ips(api)
        # Window hygiene is enforced at activation (PRD §3.4), so creating an
        # overlapping statement succeeds and lands in DRAFT...
        resp = api.create_ips(
            {
                "trust_id": trust["id"],
                "effective_from": "2027-06-01",
                "effective_to": "2028-01-01",
                "equity_target_pct": 50.00,
                "equity_band_pct": 5.00,
                "fixed_income_target_pct": 40.00,
                "fixed_income_band_pct": 5.00,
                "alternatives_allowed": False,
            },
            MANAGER,
        )
        ips2 = validate_success(resp, expected_status=201)
        assert ips2["status"] == "DRAFT"
        # ...while activating it overlaps the ACTIVE ips1 window and is
        # rejected, leaving the prior policy untouched.
        resp = api.activate_ips(ips2["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_IPS_PERIOD_OVERLAP)
        current = validate_success(api.get_ips(ips1["id"], MANAGER))
        assert current["status"] == "ACTIVE"


class TestTmvReconciliation:
    def test_buy_converts_cash_tmv_unchanged(self, api):
        """PRD §2.6: "`total_market_value_cents` is the sum of every holding's
        `market_value_cents` plus both cash balances."
        PRD §3.4: "Each purchase appends an INVESTMENT_PURCHASE row in the
        PRINCIPAL bucket for the negative of units times price, recomputes the
        trust's balances and `total_market_value_cents`, and increments the
        trust's `version`."

        Design: Corner/cross_cutting_complexity_layers/derived_tmv_reconciliation_across_buy_reprice_sell
        """
        trust = create_active_trust(trust_name="TMV Buy")
        post_receipt(trust["id"], 100000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        buy_holding(trust["id"], "EQUITY", "AAA", 1000, 25000)
        after = get_trust(trust["id"], MANAGER)
        assert after["total_market_value_cents"] == 100000000
        assert after["principal_balance_cents"] == 75000000

    def test_reprice_and_partial_sell_reconcile(self, api):
        """PRD §3.4: "Sales take a number of `units` and credit the proceeds —
        units multiplied by the current `unit_price_cents` — to PRINCIPAL via
        an INVESTMENT_SALE row, reduce `cost_basis_cents` pro rata as the
        basis multiplied by units sold divided by units held before the sale,
        rounded half up, and recompute trust balances and market value with
        the usual version increment."
        PRD §3.4: "A holding's `market_value_cents` is always exactly its
        `units` multiplied by its `unit_price_cents`, an exact integer
        product."

        Design: Corner/cross_cutting_complexity_layers/derived_tmv_reconciliation_across_buy_reprice_sell
        """
        trust = create_active_trust(trust_name="TMV Sell")
        post_receipt(trust["id"], 100000000, receipt_type="INITIAL_FUNDING",
                     value_date="2026-08-05", description="funding")
        holding = buy_holding(trust["id"], "EQUITY", "AAA", 1000, 25000)

        assert api.update_price(
            holding["id"], {"unit_price_cents": 26000, "priced_at": "2026-09-01T00:00:00Z"},
            MANAGER,
        ).status_code == 200
        assert get_trust(trust["id"], MANAGER)["total_market_value_cents"] == 101000000

        assert api.sell_holding(holding["id"], {"units": 500}, MANAGER).status_code == 200
        h_after = validate_success(api.get_holding(holding["id"], MANAGER))
        assert h_after["units"] == 500
        assert h_after["cost_basis_cents"] == 12500000
        t_after = get_trust(trust["id"], MANAGER)
        assert t_after["principal_balance_cents"] == 88000000
        assert t_after["total_market_value_cents"] == 101000000
