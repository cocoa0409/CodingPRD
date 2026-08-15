"""Financing applications: debt-service variants, the DSCR boundary, LTV,
validation priority on commit, and the financing-contingency window."""
from test_helpers import (
    ApiErrorId,
    create_deal,
    create_financing_application_payload,
    set_clock,
    setup_psa_executed,
    validate_error,
    validate_success,
)


class TestAnnualDebtServiceVariants:
    def test_interest_only_debt_service(self, api, capital_markets_headers):
        """PRD §3.9: "For an interest-only loan (`amortization_months` zero),
        the `annual_debt_service_cents` is the loan amount multiplied by the
        `interest_rate_bps` and divided by ten thousand, rounded half up to
        whole cents."

        Design: Difficulty/dual_variant_calc/annual_debt_service_interest_only_vs_amortizing_on_financing_domain
        """
        deal = create_deal(deal_name="DebtServiceDeal",
                           target_close_date="2026-11-01T00:00:00Z",
                           purchase_price_cents=25000000,
                           earnest_money_cents=500000)
        app = validate_success(api.create_financing_application(
            deal["id"],
            create_financing_application_payload(
                loan_amount_cents=15000000, interest_rate_bps=600,
                amortization_months=0),
            capital_markets_headers), 201)
        submitted = validate_success(api.submit_financing_application(
            deal["id"], app["id"], capital_markets_headers))
        # 15,000,000 * 600 / 10,000 = 900,000
        assert submitted["annual_debt_service_cents"] == 900000

    def test_amortizing_debt_service_diverges(self, api,
                                              capital_markets_headers):
        """PRD §3.9: "For an amortizing loan, the monthly rate is the
        `interest_rate_bps` divided by ten thousand and then by twelve; the
        constant monthly payment is the loan amount multiplied by that
        monthly rate and by the n-th power of one-plus-the-monthly-rate,
        divided by that same n-th power minus one, where n is the
        `amortization_months`; the payment is rounded half up to whole cents
        first, and the annual figure is that rounded payment multiplied by
        twelve — the pinned order matters and must not be reversed."

        Design: Difficulty/dual_variant_calc/annual_debt_service_interest_only_vs_amortizing_on_financing_domain
        """
        deal = create_deal(deal_name="DebtServiceDeal2",
                           target_close_date="2026-11-01T00:00:00Z",
                           purchase_price_cents=25000000,
                           earnest_money_cents=500000)
        io_app = validate_success(api.create_financing_application(
            deal["id"],
            create_financing_application_payload(
                loan_amount_cents=15000000, interest_rate_bps=600,
                amortization_months=0),
            capital_markets_headers), 201)
        am_app = validate_success(api.create_financing_application(
            deal["id"],
            create_financing_application_payload(
                loan_amount_cents=15000000, interest_rate_bps=600,
                amortization_months=300),
            capital_markets_headers), 201)
        io = validate_success(api.submit_financing_application(
            deal["id"], io_app["id"], capital_markets_headers))
        am = validate_success(api.submit_financing_application(
            deal["id"], am_app["id"], capital_markets_headers))
        # r = 0.005, n = 300: payment 96,645 -> annual 1,159,740.
        assert io["annual_debt_service_cents"] == 900000
        assert am["annual_debt_service_cents"] == 1159740
        divergence = am["annual_debt_service_cents"] - io["annual_debt_service_cents"]
        assert divergence == 259740, (
            "The amortization mode alone drives a 259,740-cent divergence")


class TestDscrBoundary:
    def _setup_boundary_deal(self):
        """NOI is pinned at 1,562,500 (lease 1,838,236 with the 15%
        conservative allowance: truncation yields exactly 1,562,500)."""
        ctx = setup_psa_executed(
            deal_name="DSCRBoundaryDeal", purchase_price_cents=20000000,
            earnest_money_cents=300000, lease_rent_cents=1838236,
            lease_expiration="2036-01-01T00:00:00Z",
            dd_period_days=45, financing_contingency_days=30,
            property_overrides={"address": "17 Boundary Way",
                                "property_type": "INDUSTRIAL",
                                "rentable_sqft": 25000, "year_built": 2014},
            tenant_overrides={"legal_name": "BTenant", "credit_score": 850,
                              "annual_revenue_cents": 200000000})
        assert ctx["model"]["noi_cents"] == 1562500, (
            f"Setup NOI pin failed: {ctx['model']['noi_cents']}")
        return ctx

    def test_dscr_exactly_1_25_passes(self, api, capital_markets_headers):
        """PRD §3.9: "The `dscr` — the latest approved model's `noi_cents`
        divided by the application's `annual_debt_service_cents`, carried to
        four decimal places with round-half-up — must be at least 1.25, with
        the boundary inclusive (exactly 1.25 passes)"
        PRD §3.3: "The arithmetic is integer multiplication followed by
        truncation to whole cents; no rounding mode applies."

        Design: Difficulty/boundary_precision_check/dscr_boundary_exactly_1_25_passes_on_financing_commit
        """
        ctx = self._setup_boundary_deal()
        deal_id = ctx["deal"]["id"]
        app = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(
                loan_amount_cents=12500000, interest_rate_bps=1000,
                amortization_months=0),
            capital_markets_headers), 201)
        submitted = validate_success(api.submit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert submitted["annual_debt_service_cents"] == 1250000
        # dscr = 1,562,500 / 1,250,000 = 1.25 exactly — the inclusive
        # boundary passes.
        committed = validate_success(api.commit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert committed["status"] == "COMMITTED"
        assert committed["committed_at"] is not None

    def test_dscr_one_cent_below_boundary_fails(self, api,
                                                capital_markets_headers):
        """PRD §3.9: "must be at least 1.25, with the boundary inclusive
        (exactly 1.25 passes); otherwise `ERR_DSCR_BELOW_MINIMUM`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/dscr_boundary_exactly_1_25_passes_on_financing_commit
        """
        ctx = self._setup_boundary_deal()
        deal_id = ctx["deal"]["id"]
        app = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(
                loan_amount_cents=12501000, interest_rate_bps=1000,
                amortization_months=0),
            capital_markets_headers), 201)
        submitted = validate_success(api.submit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert submitted["annual_debt_service_cents"] == 1250100
        # dscr = 1,562,500 / 1,250,100 = 1.2499 < 1.25.
        resp = api.commit_financing_application(deal_id, app["id"],
                                                capital_markets_headers)
        validate_error(resp, ApiErrorId.ERR_DSCR_BELOW_MINIMUM)


class TestCommitValidationPriority:
    def test_state_error_beats_dscr_on_withdrawn_from_submitted(
            self, api, capital_markets_headers):
        """PRD §2.8: "then from-state validity for the requested transition
        (the entity-specific 409 state errors), then optimistic-concurrency
        version checks (412), then segregation-of-duties (403), then
        business-safety rules, and finally the business constraint, fiscal,
        temporal, and referential gate rules described in §3."
        PRD §3.9: "Invalid from-states on any of these transitions return
        `ERR_FINANCING_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_pair_on_financing_commit
        """
        ctx = setup_psa_executed(
            deal_name="PriorityDeal1", purchase_price_cents=20000000,
            lease_rent_cents=1400000, dd_period_days=45,
            financing_contingency_days=30,
            property_overrides={"address": "11 Priority Pl",
                                "rentable_sqft": 9000, "year_built": 2009},
            tenant_overrides={"legal_name": "PTenant"})
        deal_id = ctx["deal"]["id"]
        # NOI 1,190,000 vs DS 1,300,000 -> dscr 0.915: would fail the fiscal
        # gate if the state check did not fire first.
        app = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(
                loan_amount_cents=13000000, interest_rate_bps=1000,
                amortization_months=0),
            capital_markets_headers), 201)
        validate_success(api.submit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        validate_success(api.withdraw_financing_application(
            deal_id, app["id"], capital_markets_headers))

        resp = api.commit_financing_application(deal_id, app["id"],
                                                capital_markets_headers)
        validate_error(resp, ApiErrorId.ERR_FINANCING_INVALID_STATE)
        body = resp.json()
        assert body["data"]["error_id"] != "ERR_DSCR_BELOW_MINIMUM", (
            "The from-state check (priority 5) fires before the fiscal gate "
            "(priority 17)")

    def test_state_error_beats_dscr_on_withdrawn_from_draft(
            self, api, capital_markets_headers):
        """PRD §3.9: "The officer may instead decline a submitted application
        — terminal `DECLINED` — or withdraw one from `DRAFT` or `SUBMITTED`
        into `WITHDRAWN`."
        PRD §3.9: "Invalid from-states on any of these transitions return
        `ERR_FINANCING_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_pair_on_financing_commit
        """
        ctx = setup_psa_executed(
            deal_name="PriorityDeal1b", purchase_price_cents=20000000,
            lease_rent_cents=1400000, dd_period_days=45,
            financing_contingency_days=30)
        deal_id = ctx["deal"]["id"]
        app = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(
                loan_amount_cents=13000000, interest_rate_bps=1000,
                amortization_months=0),
            capital_markets_headers), 201)
        withdrawn = validate_success(api.withdraw_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api.commit_financing_application(deal_id, app["id"],
                                                capital_markets_headers)
        validate_error(resp, ApiErrorId.ERR_FINANCING_INVALID_STATE)


class TestFinancingContingencyWindow:
    def _setup_window_deal(self, api, capital_markets_headers):
        """PSA executed 2026-08-01 with a 20-day financing contingency, so
        the commitment window closes at 2026-08-21T00:00:00Z. NOI 1,562,500
        and DS 1,250,000 give dscr exactly 1.25 so only the window matters."""
        set_clock("2026-08-01T00:00:00Z")
        ctx = setup_psa_executed(
            deal_name="WindowDeal", purchase_price_cents=20000000,
            earnest_money_cents=300000, lease_rent_cents=1838236,
            lease_expiration="2036-01-01T00:00:00Z",
            dd_period_days=45, financing_contingency_days=20,
            property_overrides={"address": "43 Window Ln",
                                "property_type": "INDUSTRIAL",
                                "rentable_sqft": 26000, "year_built": 2015},
            tenant_overrides={"legal_name": "WinTenant", "credit_score": 840})
        deal_id = ctx["deal"]["id"]
        app = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(
                loan_amount_cents=12500000, interest_rate_bps=1000,
                amortization_months=0),
            capital_markets_headers), 201)
        validate_success(api.submit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        return ctx, app

    def test_commit_at_exactly_contingency_end_succeeds(
            self, api, platform_admin_headers, capital_markets_headers):
        """PRD §3.9: "the logical clock's current instant must be no later
        than the deal's `financing_contingency_end`; a commitment attempted
        after that date is rejected with `ERR_FINANCING_CONTINGENCY_LAPSED`
        (HTTP 422)"

        Design: Difficulty/resource_temporal_overlap/financing_contingency_window_closed_interval_vs_dd_period
        """
        ctx, app = self._setup_window_deal(api, capital_markets_headers)
        deal_id = ctx["deal"]["id"]
        # "No later than" — the end instant itself is inside the window.
        set_clock("2026-08-21T00:00:00Z")
        committed = validate_success(api.commit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert committed["status"] == "COMMITTED", (
            "Commit at exactly financing_contingency_end succeeds "
            "(closed-right window)")

    def test_past_window_application_lapses_then_commit_is_invalid_state(
            self, api, platform_admin_headers, capital_markets_headers):
        """PRD §2.6: "a financing application still sitting in `SUBMITTED`
        when the clock passes the deal's `financing_contingency_end` lapses
        to `LAPSED`, which marks the financing milestone `OVERDUE`"
        PRD §3.9: "Invalid from-states on any of these transitions return
        `ERR_FINANCING_INVALID_STATE`."
        PRD §2.8: "then from-state validity for the requested transition (the
        entity-specific 409 state errors), then optimistic-concurrency
        version checks (412), then segregation-of-duties (403), then
        business-safety rules, and finally the business constraint, fiscal,
        temporal, and referential gate rules"

        Design: Difficulty/resource_temporal_overlap/financing_contingency_window_closed_interval_vs_dd_period
        """
        ctx, app = self._setup_window_deal(api, capital_markets_headers)
        deal_id = ctx["deal"]["id"]
        # One second past the window end, the clock-set itself lapses the
        # still-SUBMITTED application.
        set_clock("2026-08-21T00:00:01Z")
        app_after = validate_success(api.get_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert app_after["status"] == "LAPSED"

        # Committing the now-LAPSED application hits the from-state check,
        # which the fixed validation order evaluates before temporal rules.
        resp = api.commit_financing_application(deal_id, app["id"],
                                                capital_markets_headers)
        validate_error(resp, ApiErrorId.ERR_FINANCING_INVALID_STATE)


class TestLtvCeiling:
    def test_error_ltv_exceeded_triggerable(self, api,
                                            capital_markets_headers):
        """PRD §3.9: "Submission validates the loan-to-value ceiling: the
        `loan_amount_cents` must be no more than sixty-five percent of the
        PSA's `psa_price_cents`, else `ERR_LTV_EXCEEDED` (HTTP 422)."

        Design: Corner/errors/error_ltv_exceeded_triggerable
        """
        ctx = setup_psa_executed(deal_name="LTVDeal",
                                 purchase_price_cents=20000000,
                                 earnest_money_cents=300000,
                                 lease_rent_cents=1500000,
                                 dd_period_days=30,
                                 financing_contingency_days=20)
        deal_id = ctx["deal"]["id"]
        # 65% of 20,000,000 is 13,000,000.
        over = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(loan_amount_cents=13000001),
            capital_markets_headers), 201)
        resp = api.submit_financing_application(deal_id, over["id"],
                                                capital_markets_headers)
        validate_error(resp, ApiErrorId.ERR_LTV_EXCEEDED)

        at_cap = validate_success(api.create_financing_application(
            deal_id,
            create_financing_application_payload(loan_amount_cents=13000000),
            capital_markets_headers), 201)
        submitted = validate_success(api.submit_financing_application(
            deal_id, at_cap["id"], capital_markets_headers))
        assert submitted["status"] == "SUBMITTED", (
            "Exactly 65% passes the LTV ceiling (inclusive)")
