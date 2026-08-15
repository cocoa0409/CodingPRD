"""Invoicing: PROVISIONAL vs FINAL variants, shortage credit modes, tiered fuel
escalation, pinned per-day rounding, monthly cap truncation, dispute loop, and
the district outstanding balance."""
from test_helpers import (
    ApiErrorId,
    build_service_day,
    create_active_contract,
    create_completed_charter,
    create_district,
    create_fuel_entry,
    generate_invoice,
    get_success_data,
    issue_invoice,
    make_district_admin_headers,
    set_clock,
    setup_billing_scenario,
    setup_ops_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import FLEET, FINANCE, OPS


class TestInvoiceProvisionalVsFinal:
    def _setup_mixed_period(self, api):
        ctx = setup_billing_scenario(
            district_name="D-DV1",
            contract_overrides={"bid_reference": "BID-DV1"},
            routes=[(420, 480, 40), (480, 540, 30)],
            completed_days=[("2026-06-01", 60)],
            locked_days=["2026-06-02"],
            fuel_price=400)
        return ctx, ctx["invoices"][0]

    def test_provisional_bills_locked_day_at_planned_coverage(self, api):
        """PRD section 3.7: "Its `bus_lines_cents` sums one line per qualifying
        service day: for days in `RECONCILED` or `INVOICED`, the count of
        assignments with `billable` true multiplied by the contract's
        `daily_rate_per_bus_cents`; for days still `LOCKED`, the planned
        `required_routes` multiplied by the daily rate — optimistic billing at
        planned coverage."
        PRD section 3.7: "The provisional total is recorded as
        `provisional_total_cents` and, while the invoice stands `DRAFT`, the
        authoritative `total_cents` equals it; `final_total_cents` stays null
        until issue."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_billing
        """
        _ctx, invoice = self._setup_mixed_period(api)
        assert invoice["status"] == "DRAFT"
        # RECONCILED day bills 2 billable x 50000; LOCKED day bills 2 planned
        # x 50000 optimistically.
        assert invoice["bus_lines_cents"] == 200000
        assert invoice["provisional_total_cents"] == 200000
        assert invoice["total_cents"] == 200000
        assert invoice["final_total_cents"] is None
        assert invoice["fuel_adjustment_cents"] == 0, (
            "average 400 is below the 400 x 1.05 = 420 trigger")

    def test_issue_recomputes_final_and_cascades(self, api):
        """PRD section 3.7: "Issuing is the point of finality. A `FinanceClerk`
        issues a `DRAFT` invoice, moving it to `ISSUED`; the FINAL variant is
        recomputed from scratch — only `RECONCILED` days bill, at their
        `billable` assignment counts, with `LOCKED` days contributing nothing
        and shortage credit drawn from `RECONCILED` days only — and recorded as
        `final_total_cents`, which becomes the authoritative `total_cents`. The
        `issued_on` date is taken from the logical clock, every `RECONCILED`
        service day in the period cascades to `INVOICED`, every `COMPLETED`
        charter in the period cascades to `INVOICED`, and the district's
        outstanding balance is recomputed."

        Design: Difficulty/dual_variant_calc/invoice_provisional_vs_final_billing
        """
        ctx, invoice = self._setup_mixed_period(api)
        issued = issue_invoice(invoice["id"])
        assert issued["status"] == "ISSUED"
        assert issued["final_total_cents"] == 100000, (
            "FINAL bills the RECONCILED day only: 2 billable x 50000")
        assert issued["total_cents"] == 100000

        day1 = validate_success(api.get_service_day(
            ctx["reconciled_days"][0]["id"], OPS))
        assert day1["status"] == "INVOICED", "issue cascade"
        day2 = validate_success(api.get_service_day(ctx["locked_days"][0]["id"], OPS))
        assert day2["status"] == "LOCKED", (
            "unreconciled day neither billed finally nor flipped")


class TestShortagePenaltyVariants:
    def _setup_uncovered_reconciled_day(self, api, penalty_mode, name):
        ctx = setup_ops_scenario(
            district_name=name,
            contract_overrides={"penalty_mode": penalty_mode},
            routes=[(420, 480, 40)], with_driver=False, with_bus=False)
        day, _assignments = build_service_day(
            ctx["contract"]["id"], "2026-06-01", lock=True, reconcile=True)
        return ctx, day

    def test_flat_per_route_credit(self, api):
        """PRD section 3.5: "The day's `shortage_credit_cents` is computed per
        the contract's `penalty_mode`: under `FLAT_PER_ROUTE`, the uncovered
        count multiplied by `shortage_penalty_flat_cents`; under
        `PER_STUDENT_MINUTE`, the sum over each uncovered assignment of its
        route's `student_count` multiplied by
        `assumed_minutes_per_missed_route` multiplied by
        `shortage_penalty_per_student_minute_cents`."

        Design: Difficulty/dual_variant_calc/shortage_penalty_flat_vs_student_minute
        """
        _ctx, day = self._setup_uncovered_reconciled_day(api, "FLAT_PER_ROUTE",
                                                         "D-SP-A")
        assert day["status"] == "RECONCILED"
        assert day["uncovered_routes"] == 1
        assert day["shortage_credit_cents"] == 15000, "1 uncovered x 15000 flat"

    def test_per_student_minute_credit_diverges(self, api):
        """PRD section 3.5: "The day's `shortage_credit_cents` is computed per
        the contract's `penalty_mode`: under `FLAT_PER_ROUTE`, the uncovered
        count multiplied by `shortage_penalty_flat_cents`; under
        `PER_STUDENT_MINUTE`, the sum over each uncovered assignment of its
        route's `student_count` multiplied by
        `assumed_minutes_per_missed_route` multiplied by
        `shortage_penalty_per_student_minute_cents`."

        Design: Difficulty/dual_variant_calc/shortage_penalty_flat_vs_student_minute
        """
        _ctx, day = self._setup_uncovered_reconciled_day(api, "PER_STUDENT_MINUTE",
                                                         "D-SP-B")
        assert day["uncovered_routes"] == 1
        # 40 students x 45 assumed minutes x 25 cents.
        assert day["shortage_credit_cents"] == 45000
        assert day["shortage_credit_cents"] != 15000, (
            "same shortage data, variant-selected divergence")


class TestFuelEscalationTieredFormula:
    def _setup_tiered_invoice(self, api):
        ctx = setup_billing_scenario(
            district_name="D-FUEL1",
            contract_overrides={"bid_reference": "BID-F1"},
            mpg_x10=50, fuel_price=455,
            completed_days=[("2026-06-01", 100), ("2026-06-02", 150)])
        return ctx, ctx["invoices"][0]

    def test_tiered_per_gallon_rate_applies(self, api):
        """PRD section 3.7: "When triggered, the excess over base splits into
        two tiers: tier one is the excess capped at the whole-cent floor of ten
        percent of the base, and tier two is whatever remains. Each tier earns
        its own per-gallon rate — tier one's excess times
        `fuel_escalation_share_pct` hundredths, rounded half-up to a whole cent;
        tier two's excess times a share of one-and-a-half times
        `fuel_escalation_share_pct` capped at one hundred percent, hundredths,
        rounded half-up — and the per-gallon adjustment is their sum."
        PRD section 3.7: "Fuel consumed per service day is reckoned in
        thousandths of a gallon: for every `COMPLETED` assignment on the day, and
        every `COMPLETED` charter whose `trip_date` equals the day's date, the
        `actual_miles` times ten thousand divided by the bus's `mpg_x10`, floored
        to a whole number."

        Design: Difficulty/combinatorial_formula/fuel_escalation_tiered_formula
        """
        _ctx, invoice = self._setup_tiered_invoice(api)
        # excess = 455 - 400 = 55; tier1 = min(55, 40) = 40 -> 32c;
        # tier2 = 15 at min(100, 120)% -> 15c; 47c/gal.
        # day1: floor(100*10000/50) = 20000 milli-gal -> 940c;
        # day2: 30000 milli-gal -> 1410c.
        assert invoice["fuel_adjustment_cents"] == 2350, "940 + 1410"

    def test_invoice_totals_with_escalation(self, api):
        """PRD section 3.7: "First `bus_lines_cents`, then
        `charter_lines_cents`, then `shortage_credit_cents` is subtracted,
        yielding a preliminary total. The raw fuel adjustment is computed next."
        PRD section 3.7: "Its `bus_lines_cents` sums one line per qualifying
        service day: for days in `RECONCILED` or `INVOICED`, the count of
        assignments with `billable` true multiplied by the contract's
        `daily_rate_per_bus_cents`"

        Design: Difficulty/combinatorial_formula/fuel_escalation_tiered_formula
        """
        _ctx, invoice = self._setup_tiered_invoice(api)
        assert invoice["bus_lines_cents"] == 100000, "2 reconciled days x 50000"
        assert invoice["charter_lines_cents"] == 0
        assert invoice["shortage_credit_cents"] == 0
        assert invoice["total_cents"] == 102350


class TestFuelDailyRoundingPinned:
    def _setup_rounding_invoice(self, api):
        ctx = setup_billing_scenario(
            district_name="D-FUEL2",
            contract_overrides={"bid_reference": "BID-F2"},
            mpg_x10=30, fuel_price=455,
            completed_days=[("2026-06-01", 100), ("2026-06-02", 100)])
        return ctx, ctx["invoices"][0]

    def test_per_day_rounding_then_sum(self, api):
        """PRD section 3.7: "The day's fuel adjustment is those thousandths of a
        gallon times the per-gallon adjustment, divided by one thousand, rounded
        half-up to whole cents — and the rounding order is pinned: each day is
        rounded individually, then the rounded day amounts are summed. Summing
        all gallons first and rounding once is forbidden, because the two orders
        produce different cents."

        Design: Difficulty/combinatorial_formula/fuel_daily_rounding_order_pinned
        """
        _ctx, invoice = self._setup_rounding_invoice(api)
        # Each day: floor(100*10000/30) = 33333 milli-gal; 33333 x 47 / 1000 =
        # 1566.651 -> 1567 rounded half-up; 1567 + 1567.
        assert invoice["fuel_adjustment_cents"] == 3134

    def test_sum_then_round_would_differ(self, api):
        """PRD section 3.7: "The day's fuel adjustment is those thousandths of a
        gallon times the per-gallon adjustment, divided by one thousand, rounded
        half-up to whole cents — and the rounding order is pinned: each day is
        rounded individually, then the rounded day amounts are summed. Summing
        all gallons first and rounding once is forbidden, because the two orders
        produce different cents."

        Design: Difficulty/combinatorial_formula/fuel_daily_rounding_order_pinned
        """
        _ctx, invoice = self._setup_rounding_invoice(api)
        assert invoice["fuel_adjustment_cents"] != 3133, (
            "the forbidden sum-then-round order would produce 3133")
        assert invoice["total_cents"] == 103134, "100000 + 3134"


class TestInvoiceCapTruncatesFuel:
    def _setup_capped_invoice(self, api):
        ctx = setup_billing_scenario(
            district_name="D-CAP",
            contract_overrides={"bid_reference": "BID-CAP",
                                "monthly_cap_cents": 100500},
            mpg_x10=50, fuel_price=455,
            completed_days=[("2026-06-01", 100), ("2026-06-02", 100)])
        return ctx, ctx["invoices"][0]

    def test_cap_truncates_fuel_adjustment(self, api):
        """PRD section 3.7: "If the preliminary total plus the raw adjustment
        would exceed `monthly_cap_cents`, the recorded `fuel_adjustment_cents`
        is truncated to the larger of zero and the cap minus the preliminary
        total; otherwise it is the raw adjustment."

        Design: Difficulty/combinatorial_formula/invoice_cap_truncates_fuel_adjustment
        """
        _ctx, invoice = self._setup_capped_invoice(api)
        # preliminary 100000; raw fuel 2 x 940 = 1880; truncated to
        # 100500 - 100000.
        assert invoice["fuel_adjustment_cents"] == 500

    def test_total_lands_on_cap(self, api):
        """PRD section 3.7: "If the preliminary total plus the raw adjustment
        would exceed `monthly_cap_cents`, the recorded `fuel_adjustment_cents`
        is truncated to the larger of zero and the cap minus the preliminary
        total; otherwise it is the raw adjustment. The invoice total is the
        preliminary total plus the recorded fuel adjustment."

        Design: Difficulty/combinatorial_formula/invoice_cap_truncates_fuel_adjustment
        """
        _ctx, invoice = self._setup_capped_invoice(api)
        assert invoice["bus_lines_cents"] == 100000
        assert invoice["total_cents"] == 100500, "lands exactly on monthly_cap_cents"


class TestFuelTriggerInclusiveThreshold:
    def _setup_boundary_invoices(self, api):
        ctx = setup_ops_scenario(district_name="D-BND1",
                                 contract_overrides={"bid_reference": "BID-B1"},
                                 bus_overrides={"mpg_x10": 50})
        for date in ("2026-06-01", "2026-07-01"):
            build_service_day(ctx["contract"]["id"], date, ctx["driver"]["id"],
                              ctx["bus"]["id"], run_miles=100, lock=True,
                              reconcile=True)
        create_fuel_entry(ctx["district"]["id"], "2026-06", 420)
        create_fuel_entry(ctx["district"]["id"], "2026-07", 419)
        inv_june = generate_invoice(ctx["contract"]["id"], "2026-06")
        inv_july = generate_invoice(ctx["contract"]["id"], "2026-07")
        return ctx, inv_june, inv_july

    def test_price_at_exact_threshold_triggers(self, api):
        """PRD section 3.7: "The trigger comparison is integer-exact: if one
        hundred times the average is less than the base multiplied by one
        hundred plus `fuel_escalation_trigger_pct`, the adjustment is zero for
        every day; an average of exactly the base increased by the trigger
        percentage does trigger."

        Design: Difficulty/boundary_precision_check/fuel_trigger_inclusive_threshold
        """
        _ctx, inv_june, _inv_july = self._setup_boundary_invoices(api)
        # 420 x 100 == 400 x 105 exactly: triggers. excess 20 within tier 1 ->
        # 16c/gal; 20.000 gal -> 320c.
        assert inv_june["fuel_adjustment_cents"] == 320
        assert inv_june["total_cents"] == 50320

    def test_one_cent_below_threshold_yields_zero(self, api):
        """PRD section 3.7: "The trigger comparison is integer-exact: if one
        hundred times the average is less than the base multiplied by one
        hundred plus `fuel_escalation_trigger_pct`, the adjustment is zero for
        every day; an average of exactly the base increased by the trigger
        percentage does trigger."

        Design: Difficulty/boundary_precision_check/fuel_trigger_inclusive_threshold
        """
        _ctx, _inv_june, inv_july = self._setup_boundary_invoices(api)
        # 419 x 100 = 41900 < 42000: one cent below the threshold.
        assert inv_july["fuel_adjustment_cents"] == 0
        assert inv_july["total_cents"] == 50000


class TestInvoiceDisputeReissueCycle:
    def _setup_issued(self, api):
        ctx = setup_billing_scenario(
            district_name="D-DISP",
            contract_overrides={"bid_reference": "BID-DISP"},
            issue=True, issue_clock="2026-06-05T00:00:00Z")
        return ctx, ctx["invoices"][0]

    def test_dispute_moves_invoice_to_disputed(self, api):
        """PRD section 3.7: "The owning `DistrictAdmin` may dispute it — moving
        `ISSUED` to `DISPUTED` with a required `reason` — provided the clock
        date is no later than `issued_on` plus the district's
        `billing_dispute_window_days`; that last day is still inside the window,
        and any later attempt is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. Each
        dispute increments `dispute_count` and records the reason in
        `dispute_reason`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle
        """
        ctx, invoice = self._setup_issued(api)
        assert invoice["total_cents"] == 50000
        disputed = get_success_data(api.dispute_invoice(
            invoice["id"], {"reason": "Shortage credit miscalculated"},
            make_district_admin_headers(ctx["district"]["id"])))
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_count"] == 1
        assert disputed["dispute_reason"] == "Shortage credit miscalculated"

    def test_reissue_applies_delta_and_refreshes(self, api):
        """PRD section 3.7: "Resolution loops back: the `FinanceClerk` reissues
        a `DISPUTED` invoice to `ISSUED` with an `adjustment_delta_cents` — which
        may be negative — and a `reason`; the delta is added to both
        `total_cents` and `final_total_cents`, `issued_on` refreshes to the
        clock date, and the district's balance recomputes."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_reissue_cycle
        """
        ctx, invoice = self._setup_issued(api)
        get_success_data(api.dispute_invoice(
            invoice["id"], {"reason": "Shortage credit miscalculated"},
            make_district_admin_headers(ctx["district"]["id"])))
        reissued = get_success_data(api.reissue_invoice(
            invoice["id"], {"adjustment_delta_cents": -5000,
                            "reason": "Agreed credit correction"}, FINANCE))
        assert reissued["status"] == "ISSUED", "cycle completed"
        assert reissued["total_cents"] == 45000, "50000 - 5000 delta"
        assert reissued["final_total_cents"] == 45000
        assert reissued["dispute_count"] == 1
        assert reissued["issued_on"] == "2026-06-05", (
            "refreshed at reissue from the logical clock")


class TestPaidInvoiceTerminal:
    def test_terminal_lockdown_paid_invoice_returns_409(self, api):
        """PRD section 3.7: "Payment moves `ISSUED` to terminal `PAID`, stamps
        `paid_on` from the clock, and recomputes the balance."
        PRD section 2.8: "8. **Terminal-state rejection.** An entity already in a
        terminal state — `TERMINATED`, `PAID`, `WRITTEN_OFF`, `CLOSED`,
        `COMPLETED`, `NO_SHOW`, `CANCELLED`, `EXPIRED`, `DECOMMISSIONED`,
        `INVOICED`, `DECLINED`, as applicable per resource — accepts no further
        transitions; attempts yield `ERR_ALREADY_TERMINAL` (HTTP 409)."

        Design: Corner/state_machines/terminal_lockdown_paid_invoice_returns_409
        """
        ctx = setup_billing_scenario(
            district_name="D-SM3",
            contract_overrides={"bid_reference": "BID-S3"},
            issue=True, issue_clock="2026-06-05T00:00:00Z")
        invoice = ctx["invoices"][0]
        paid = get_success_data(api.pay_invoice(invoice["id"], FINANCE))
        assert paid["status"] == "PAID"

        resp = api.dispute_invoice(
            invoice["id"], {"reason": "too late"},
            make_district_admin_headers(ctx["district"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)
        fetched = validate_success(api.get_invoice(invoice["id"], FINANCE))
        assert fetched["status"] == "PAID"
        assert fetched["dispute_count"] == 0


class TestDisputeWindowBoundary:
    def test_error_dispute_window_closed_boundary(self, api):
        """PRD section 3.7: "The owning `DistrictAdmin` may dispute it — moving
        `ISSUED` to `DISPUTED` with a required `reason` — provided the clock
        date is no later than `issued_on` plus the district's
        `billing_dispute_window_days`; that last day is still inside the window,
        and any later attempt is rejected with `ERR_DISPUTE_WINDOW_CLOSED`."

        Design: Corner/errors/error_dispute_window_closed_boundary
        """
        ctx = setup_billing_scenario(
            district_name="D-ERR22",
            contract_overrides={"bid_reference": "BID-E22"},
            issue=True, issue_clock="2026-06-05T00:00:00Z", num_invoices=2)
        inv1, inv2 = ctx["invoices"]
        assert inv1["issued_on"] == "2026-06-05"
        district_headers = make_district_admin_headers(ctx["district"]["id"])

        # issued_on + 30 days exactly is the last day inside the window.
        set_clock("2026-07-05T00:00:00Z")
        disputed = get_success_data(api.dispute_invoice(
            inv1["id"], {"reason": "On the last day"}, district_headers))
        assert disputed["status"] == "DISPUTED"

        set_clock("2026-07-06T00:00:00Z")
        resp = api.dispute_invoice(inv2["id"], {"reason": "One day late"},
                                   district_headers)
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED, 409)


class TestDistrictOutstandingReconciliation:
    def test_district_outstanding_reconciliation(self, api):
        """PRD section 3.7: "The district's `outstanding_balance_cents` is the
        sum of `total_cents` over all its `ISSUED` invoices across every
        contract — unpaid and not written off — and it is recomputed at issue,
        reissue, payment, and write-off."

        Design: Corner/calculations/district_outstanding_reconciliation
        """
        ctx = setup_billing_scenario(district_name="D-CALC5",
                                     contract_overrides={"bid_reference": "BID-CA5"},
                                     issue=True)
        district_id = ctx["district"]["id"]
        after_issue = validate_success(api.get_district(district_id, FINANCE))
        assert after_issue["outstanding_balance_cents"] == 50000, (
            "ISSUED invoice enters outstanding")

        get_success_data(api.pay_invoice(ctx["invoices"][0]["id"], FINANCE))
        after_pay = validate_success(api.get_district(district_id, FINANCE))
        assert after_pay["outstanding_balance_cents"] == 0, (
            "PAID removes it; recomputed, not cached")


class TestIssueCascadesChildren:
    def test_issue_cascades_children_to_invoiced(self, api):
        """PRD section 3.7: "The `issued_on` date is taken from the logical
        clock, every `RECONCILED` service day in the period cascades to
        `INVOICED`, every `COMPLETED` charter in the period cascades to
        `INVOICED`, and the district's outstanding balance is recomputed."
        PRD section 3.7: "`charter_lines_cents` sums the `final_price_cents` of
        the contract's `COMPLETED` charters whose `trip_date` falls in the
        period."

        Design: Corner/endpoints/issue_cascades_children_to_invoiced
        """
        ctx = setup_ops_scenario(district_name="D-EP3",
                                 contract_overrides={"bid_reference": "BID-EP3"})
        day, _asgs = build_service_day(
            ctx["contract"]["id"], "2026-06-01", ctx["driver"]["id"],
            ctx["bus"]["id"], run_miles=60, lock=True, reconcile=True)
        charter = create_completed_charter(
            ctx["contract"]["id"], ctx["district"]["id"], ctx["bus"]["id"],
            actual_hours_x10=20, actual_miles=40, purpose="Invoice me")
        # floor(20 x 12000 / 10) + 40 x 250 = 24000 + 10000.
        assert charter["final_price_cents"] == 34000
        create_fuel_entry(ctx["district"]["id"], "2026-06", 400)
        invoice = generate_invoice(ctx["contract"]["id"], "2026-06")

        issued = issue_invoice(invoice["id"])
        assert issued["charter_lines_cents"] == 34000

        day_after = validate_success(api.get_service_day(day["id"], OPS))
        assert day_after["status"] == "INVOICED", "issue cascade"
        charter_after = validate_success(api.get_charter_trip(charter["id"], OPS))
        assert charter_after["status"] == "INVOICED", "issue cascade"


class TestInvoiceGates:
    def test_error_fuel_entry_missing_on_generate_returns_422(self, api):
        """PRD section 3.7: "Two gates apply up front: a fuel price entry must
        exist for the contract's district and the billed period (else
        `ERR_FUEL_ENTRY_MISSING`, HTTP 422), and the period must contain at
        least one `RECONCILED` service day — something final to bill — else
        generation fails with `ERR_INVOICE_PERIOD_INCOMPLETE` (HTTP 422)."

        Design: Corner/errors/error_fuel_entry_missing_on_generate_returns_422
        """
        ctx = setup_ops_scenario(district_name="D-ERR3",
                                 contract_overrides={"bid_reference": "BID-E3"})
        build_service_day(ctx["contract"]["id"], "2026-06-01", lock=True,
                          reconcile=True)

        resp = api.generate_invoice(
            {"contract_id": ctx["contract"]["id"], "period_month": "2026-06"},
            FINANCE)
        validate_error(resp, ApiErrorId.ERR_FUEL_ENTRY_MISSING, 422)

    def test_error_fuel_entry_duplicate_month_triggerable(self, api):
        """PRD section 3.7: "a `FinanceClerk` records each month's index price
        as a FuelPriceEntry carrying the `district_id`, the `effective_month` —
        unique per district, so a second entry for the same district and month
        is rejected with `ERR_FUEL_ENTRY_DUPLICATE_MONTH` — the
        `avg_price_cents_per_gallon`, and a `source` reference such as an EIA
        PADD designation."

        Design: Corner/errors/error_fuel_entry_duplicate_month_triggerable
        """
        district = create_district(name="D-ERR2")
        create_fuel_entry(district["id"], "2026-06", 400)

        resp = api.create_fuel_price_entry(
            {"district_id": district["id"], "effective_month": "2026-06",
             "avg_price_cents_per_gallon": 410, "source": "EIA-REV"},
            FINANCE)
        validate_error(resp, ApiErrorId.ERR_FUEL_ENTRY_DUPLICATE_MONTH, 409)

    def test_error_invoice_period_incomplete_returns_422(self, api):
        """PRD section 3.7: "Two gates apply up front: a fuel price entry must
        exist for the contract's district and the billed period (else
        `ERR_FUEL_ENTRY_MISSING`, HTTP 422), and the period must contain at
        least one `RECONCILED` service day — something final to bill — else
        generation fails with `ERR_INVOICE_PERIOD_INCOMPLETE` (HTTP 422)."

        Design: Corner/errors/error_invoice_period_incomplete_returns_422
        """
        district = create_district(name="D-ERR26")
        contract = create_active_contract(district["id"], bid_reference="BID-E26")
        create_fuel_entry(district["id"], "2026-08", 400)

        resp = api.generate_invoice(
            {"contract_id": contract["id"], "period_month": "2026-08"}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVOICE_PERIOD_INCOMPLETE, 422)


class TestInvoiceRoleDenial:
    def test_rbac_fleet_manager_cannot_generate_invoice_returns_403(self, api):
        """PRD section 2.1: "A request whose role is not in the endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD section 4: POST /busops/invoices/generate is authorized for
        FinanceClerk only.

        Design: Corner/rbac/rbac_fleet_manager_cannot_generate_invoice_returns_403
        """
        district = create_district(name="D-RB4")
        contract = create_active_contract(district["id"], bid_reference="BID-R4")

        resp = api.generate_invoice(
            {"contract_id": contract["id"], "period_month": "2026-06"}, FLEET)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
