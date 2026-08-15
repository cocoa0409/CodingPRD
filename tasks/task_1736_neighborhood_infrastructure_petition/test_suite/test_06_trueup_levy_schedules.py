"""Preliminary and final levy allocation, true-up settlements, and installment
schedules (PRD §3.3, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_change_order,
    assert_same_instant,
    billing_run,
    complete_construction,
    complete_phase,
    drive_to_billing,
    drive_to_construction,
    drive_to_hearing_scheduled,
    finalize_true_up,
    get_assessment,
    list_district_assessments,
    list_district_invoices,
    post_payment,
    propose_change_order,
    select_payment_option,
    set_clock,
    api_client,
    validate_error,
)

FINANCE = TEST_USERS["finance_headers"]

FOUR_PARCEL_FRONTAGES = (50.0, 75.0, 25.0, 50.0)


class TestPreliminaryAllocationVariants:
    def test_front_foot_allocation_amounts(self, api):
        """PRD §3.3: "Under `FRONT_FOOT`, a per-foot rate is computed first:
        the estimate total divided by the summed `frontage_ft` of the
        participating parcels, rounded half-up to four decimal places; each
        parcel's raw amount is then its own frontage times that rate, rounded
        half-up to whole cents." and "After reconciliation the allocated
        amounts sum to the estimate total exactly."

        Design: Difficulty/dual_variant_calc/assessment_methodology_front_foot_vs_per_parcel
        """
        ctx = drive_to_hearing_scheduled(
            "DV1-FF", frontages=FOUR_PARCEL_FRONTAGES, prefix="ff",
            methodology="FRONT_FOOT", contract_price_cents=10000000,
            contingency_cents=500000, venue="City Hall Room A",
            sign_slice=(0, 1, 3),
        )
        # Locked total 10,500,000 over 200.00 ft -> rate 52,500.0000 cents/ft.
        amounts = [a["preliminary_amount_cents"]
                   for a in list_district_assessments(ctx["district"]["id"])]
        assert amounts == [2625000, 3937500, 1312500, 2625000]
        assert sum(amounts) == 10500000

    def test_per_parcel_allocation_amounts_diverge_from_front_foot(self, api):
        """PRD §3.3: "Under `PER_PARCEL`, a single equal share is computed —
        the estimate total divided by the participating parcel count, rounded
        half-up to whole cents — and every parcel receives that share." and
        "identical parcels generally receive different per-parcel figures at
        the two steps".

        Design: Difficulty/dual_variant_calc/assessment_methodology_front_foot_vs_per_parcel
        """
        ctx_ff = drive_to_hearing_scheduled(
            "DV1-FF", frontages=FOUR_PARCEL_FRONTAGES, prefix="ff",
            methodology="FRONT_FOOT", contract_price_cents=10000000,
            contingency_cents=500000, venue="City Hall Room A",
            sign_slice=(0, 1, 3),
        )
        ctx_pp = drive_to_hearing_scheduled(
            "DV1-PP", frontages=FOUR_PARCEL_FRONTAGES, prefix="pp",
            methodology="PER_PARCEL", contract_price_cents=10000000,
            contingency_cents=500000, venue="City Hall Room B",
            sign_slice=(0, 1, 3),
        )
        # Locked total 10,500,000 over 4 parcels -> equal share 2,625,000.
        ff = [a["preliminary_amount_cents"]
              for a in list_district_assessments(ctx_ff["district"]["id"])]
        pp = [a["preliminary_amount_cents"]
              for a in list_district_assessments(ctx_pp["district"]["id"])]
        assert pp == [2625000, 2625000, 2625000, 2625000]
        assert ff[1] != pp[1] and ff[2] != pp[2], (
            "identical cost data must yield different per-parcel levies "
            "across the two methodologies"
        )
        assert sum(ff) == 10500000 == sum(pp)


class TestPennyRemainder:
    def test_front_foot_remainder_applied_in_pinned_order(self, api):
        """PRD §3.3: "Both variants then reconcile the penny remainder
        identically: the difference between the estimate total and the sum of
        allocated amounts, which may be positive or negative, is walked off
        parcel by parcel in a pinned visiting order — `frontage_ft` descending,
        ties broken by `created_at` ascending — adding or subtracting one cent
        per parcel to match the sign of the difference until it is exhausted".
        PRD §3.3: "The rounding order is part of the contract: rate to four
        decimals first, then the per-parcel multiplication, then whole-cent
        rounding, then remainder reconciliation".

        Design: Difficulty/combinatorial_formula/front_foot_allocation_penny_remainder
        """
        ctx = drive_to_hearing_scheduled(
            "CF1", frontages=(100.0, 100.0, 100.0), prefix="cf1",
            methodology="FRONT_FOOT", contract_price_cents=1000001,
            contingency_cents=0, venue="City Hall Room A",
        )
        # Rate 1,000,001 / 300.00 -> 3,333.3367 (4dp); raw 333,333.67 ->
        # 333,334 each; sum 1,000,002 -> diff -1 applied to the tied-largest
        # frontage broken by earliest created_at (P-001).
        amounts = [a["preliminary_amount_cents"]
                   for a in list_district_assessments(ctx["district"]["id"])]
        assert amounts == [333333, 333334, 333334]
        assert sum(amounts) == 1000001, "remainder reconciled, not dropped"

    def test_front_foot_remainder_sum_equals_estimate_total(self, api):
        """PRD §3.3: "After reconciliation the allocated amounts sum to the
        estimate total exactly." and "summing raw values and rounding once at
        the end yields different cents and is wrong."

        Design: Difficulty/combinatorial_formula/front_foot_allocation_penny_remainder
        """
        ctx = drive_to_hearing_scheduled(
            "CF1", frontages=(100.0, 100.0, 100.0), prefix="cf1",
            methodology="FRONT_FOOT", contract_price_cents=1000001,
            contingency_cents=0, venue="City Hall Room A",
        )
        assessments = list_district_assessments(ctx["district"]["id"])
        assert len(assessments) == 3
        # Rounding raw once would give 333,334 for every parcel and a total of
        # 1,000,002; the pinned procedure forces the -1 cent onto P-001.
        assert assessments[0]["preliminary_amount_cents"] == 333333
        assert sum(a["preliminary_amount_cents"] for a in assessments) == 1000001

    def test_per_parcel_remainder_goes_to_largest_frontage(self, api):
        """PRD §3.3: "the difference between the estimate total and the sum of
        allocated amounts, which may be positive or negative, is walked off
        parcel by parcel in a pinned visiting order — `frontage_ft` descending,
        ties broken by `created_at` ascending".

        Design: Corner/calculations/c_per_parcel_penny_remainder_largest_frontage
        """
        ctx = drive_to_hearing_scheduled(
            "CPP", frontages=(30.0, 50.0, 20.0), prefix="cpp",
            methodology="PER_PARCEL", contract_price_cents=10000000,
            contingency_cents=0, venue="CPP Room",
        )
        # Share 10,000,000 / 3 -> 3,333,333 each; diff +1 applied to the
        # largest-frontage parcel (P-002, 50 ft), not to creation order.
        amounts = [a["preliminary_amount_cents"]
                   for a in list_district_assessments(ctx["district"]["id"])]
        assert amounts == [3333333, 3333334, 3333333]
        assert sum(amounts) == 10000000


class TestAmortizationSchedule:
    def _billing_ctx(self, name, prefix, **overrides):
        kwargs = dict(methodology="PER_PARCEL", contract_price_cents=100000,
                      contingency_cents=0, venue=f"{name} Room")
        kwargs.update(overrides)
        return drive_to_billing(name, prefix=prefix, option="INSTALLMENTS",
                                term_years=5, **kwargs)

    def test_level_payment_schedule_year_by_year(self, api):
        """PRD §3.7: "Otherwise the level amount is the annuity figure — the
        levy times the annual rate, divided by one minus the quantity
        one-plus-rate raised to the negative power of the term — rounded
        half-up to whole cents exactly once and held fixed thereafter. The
        schedule walks the years in order against a running balance that starts
        at the levy: each year's interest is the current balance times the
        annual rate, rounded half-up to whole cents; in every year but the
        last, the payment is the level amount and the principal portion is the
        level amount minus that year's interest".

        Design: Difficulty/combinatorial_formula/installment_amortization_level_payment_schedule
        """
        ctx = self._billing_ctx("CF2", "cf2")
        # P = 100,000, r = 4%, n = 5 -> level payment A = 22,463.
        invoices = list_district_invoices(ctx["district"]["id"])
        assert len(invoices) == 5
        components = [(inv["principal_cents"], inv["interest_cents"])
                      for inv in invoices]
        assert components == [
            (18463, 4000),
            (19202, 3261),
            (19970, 2493),
            (20768, 1695),
            (21597, 864),
        ], f"year-by-year schedule mismatch: {components}"
        assert sum(p for p, _ in components) == 100000, (
            "schedule fully amortizes the levy"
        )

    def test_final_year_absorbs_rounding_drift_and_dates(self, api):
        """PRD §3.7: "in the final year, the principal portion is whatever
        balance remains and the payment is that balance plus the year's
        interest, so the balance reaches exactly zero by construction and the
        final year absorbs all rounding drift. Each year mints one annual
        invoice — `kind` set to `ANNUAL`, `year_index` running from 1 through
        the term, `due_date` set that many 365-day years after the true-up
        instant, `issue_date` thirty days before its own due date".

        Design: Difficulty/combinatorial_formula/installment_amortization_level_payment_schedule
        """
        ctx = self._billing_ctx("CF2", "cf2")
        invoices = list_district_invoices(ctx["district"]["id"])
        year1, year5 = invoices[0], invoices[4]
        assert year1["kind"] == "ANNUAL" and year1["year_index"] == 1
        # True-up instant 2026-10-20T00:00:00Z.
        assert_same_instant(year1["due_date"], "2027-10-20T00:00:00Z", "year-1 due_date")
        assert_same_instant(year1["issue_date"], "2027-09-20T00:00:00Z", "year-1 issue_date")
        assert year5["year_index"] == 5
        assert year5["principal_cents"] + year5["interest_cents"] == 22461, (
            "final-year payment 22,461 differs from the level 22,463 "
            "(rounding drift absorption)"
        )
        assert_same_instant(year5["due_date"], "2031-10-19T00:00:00Z", "year-5 due_date")
        assert year5["status"] == "SCHEDULED"

    def test_zero_interest_rate_schedule(self, api):
        """PRD §3.7: "When the rate is zero, the level yearly amount is the
        levy divided by the number of years, rounded half-up to whole cents,
        and every year carries zero interest."

        Design: Corner/calculations/c_zero_interest_rate_schedule
        """
        ctx = self._billing_ctx("ZIR", "zir", annual_interest_rate_bp=0)
        invoices = list_district_invoices(ctx["district"]["id"])
        assert len(invoices) == 5
        for inv in invoices:
            assert inv["principal_cents"] == 20000, "100,000 / 5 years"
            assert inv["interest_cents"] == 0, "zero rate -> zero interest"
        assert invoices[0]["principal_cents"] == invoices[4]["principal_cents"], (
            "no final-year adjustment is needed at a zero rate"
        )

    def test_default_option_applied_at_trueup(self, api):
        """PRD §3.7: "Any `LEVIED` assessment whose owner never made an
        election — `payment_option` still `NONE` — is defaulted into
        `INSTALLMENTS` with a `term_years` of 10."

        Design: Corner/calculations/c_default_option_applied_at_trueup
        """
        ctx = drive_to_billing("DEF", prefix="def", methodology="PER_PARCEL",
                               contract_price_cents=100000, contingency_cents=0,
                               venue="DEF Room")
        assessment = ctx["assessments"][0]
        assert assessment["payment_option"] == "INSTALLMENTS"
        assert assessment["term_years"] == 10, "statutory default term"

        invoices = list_district_invoices(ctx["district"]["id"])
        assert len(invoices) == 10
        # A = round(100,000 * 0.04 / (1 - 1.04^-10)) = 12,329; year 1 interest
        # 4,000 -> principal 8,329.
        assert invoices[0]["principal_cents"] == 8329
        assert invoices[0]["interest_cents"] == 4000
        assert_same_instant(invoices[9]["due_date"], "2036-10-17T00:00:00Z",
                            "year-10 due_date (true-up + 10*365 days; the "
                            "2026-10-20..2036-10-20 span holds 3 leap days, so "
                            "3650 days lands on 2036-10-17)")


class TestTrueUpSupplementalInvoice:
    def test_prepaid_delta_creates_supplemental_invoice(self, api):
        """PRD §3.7: "the district's `final_total_cost_cents` becomes the
        locked estimate's `contract_price_cents` plus the cumulative
        `approved_change_total_cents` — the `contingency_cents` allowance is
        deliberately excluded from the final basis." PRD §3.7: "each
        levy-bearing assessment's `final_levy_cents`, unset until now, is set
        from it."

        Design: Corner/calculations/c_trueup_supplemental_invoice_fields
        """
        ctx = drive_to_billing(
            "TSI", prefix="tsi", methodology="PER_PARCEL",
            contract_price_cents=100000, contingency_cents=0, venue="TSI Room",
            option="PREPAY_FULL",
        )
        # Construction-phase change order of 10,000 approved before true-up is
        # exercised in a twin test below; here the base case final levy equals
        # the preliminary 100,000.
        assessment = ctx["assessments"][0]
        assert assessment["final_levy_cents"] == 100000

    def test_prepaid_delta_supplemental_fields(self, api):
        """PRD §3.7: "the district's `final_total_cost_cents` becomes the
        locked estimate's `contract_price_cents` plus the cumulative
        `approved_change_total_cents` — the `contingency_cents` allowance is
        deliberately excluded from the final basis." PRD §3.7: "when the final
        levy is strictly greater, the assessment moves to `SETTLEMENT_DUE`, its
        `principal_balance_cents` becomes the delta, and a supplemental
        **InstallmentInvoice** — `kind` set to `SUPPLEMENTAL` — is created
        directly in `ISSUED` for exactly the delta, with `year_index` 0, its
        `issue_date` at the true-up instant, its `due_date` thirty days later,
        and zero `interest_cents`".

        Design: Corner/calculations/c_trueup_supplemental_invoice_fields
        """
        ctx = drive_to_construction(
            "TSI", prefix="tsi", methodology="PER_PARCEL",
            contract_price_cents=100000, contingency_cents=0, venue="TSI Room",
        )
        district_id = ctx["district"]["id"]
        assessment = ctx["assessments"][0]
        owner = ctx["pairs"][0][0]
        select_payment_option(assessment["id"], owner["id"], option="PREPAY_FULL",
                              term_years=None)
        post_payment(assessment["id"], owner["id"], 100000)
        order = propose_change_order(district_id, amount_cents=10000,
                                     phase_id=ctx["phase"]["id"], engineer_id="eng-1")
        approve_change_order(order["id"], engineer_id="eng-2")
        complete_phase(ctx["phase"]["id"], at="2026-10-10T17:00:00Z")
        complete_construction(district_id)
        finalize_true_up(district_id, at="2026-10-20T00:00:00Z")

        invoices = list_district_invoices(district_id)
        assert len(invoices) == 1
        supplemental = invoices[0]
        assert supplemental["kind"] == "SUPPLEMENTAL"
        assert supplemental["year_index"] == 0
        assert supplemental["principal_cents"] == 10000, "final levy 110,000 less prepaid 100,000"
        assert supplemental["interest_cents"] == 0
        assert supplemental["status"] == "ISSUED"
        assert_same_instant(supplemental["issue_date"], "2026-10-20T00:00:00Z",
                            "supplemental issue_date")
        assert_same_instant(supplemental["due_date"], "2026-11-19T00:00:00Z",
                            "supplemental due_date (true-up + 30 days)")

        after = get_assessment(assessment["id"])
        assert after["status"] == "SETTLEMENT_DUE"
        assert after["principal_balance_cents"] == 10000
        assert after["final_levy_cents"] == 110000


class TestTrueUpAndBillingGates:
    def test_finalize_trueup_wrong_state_rejected(self, api):
        """PRD §3.7: "The true-up belongs to the `FinanceOfficer` and requires
        the district to be in `TRUE_UP` (`ERR_DISTRICT_NOT_IN_TRUE_UP`)."

        Design: Corner/state_machines/sm_finalize_trueup_wrong_state_rejected
        """
        ctx = drive_to_construction("SFT", prefix="sft", venue="SFT Room")
        validate_error(
            api_client.finalize_true_up(ctx["district"]["id"], FINANCE),
            ApiErrorId.ERR_DISTRICT_NOT_IN_TRUE_UP,
        )

    def test_billing_run_wrong_state_rejected(self, api):
        """PRD §3.8: "Collections are kept honest by the billing run, a
        `FinanceOfficer` operation available only while the district is in
        `BILLING` (`ERR_DISTRICT_NOT_IN_BILLING`)."

        Design: Corner/state_machines/sm_billing_run_wrong_state_rejected
        """
        ctx = drive_to_construction("SBR", prefix="sbr", venue="SBR Room")
        # District is in CONSTRUCTION (i.e. past APPROVED, before TRUE_UP);
        # the state gate must fire.
        validate_error(
            api_client.billing_run(ctx["district"]["id"], FINANCE),
            ApiErrorId.ERR_DISTRICT_NOT_IN_BILLING,
        )

    def test_billing_run_idempotent_at_same_clock(self, api):
        """PRD §3.8: "Either way, `penalty_cents` is recomputed idempotently
        from the overdue month count at every run and never incremented
        piecemeal, so repeated runs at the same clock reading are no-ops." PRD
        §3.8: "The run answers with `issued_count`, `newly_delinquent_count`,
        and `cured_count`".

        Design: Corner/endpoints/ep_billing_run_idempotent_same_clock
        """
        ctx = drive_to_billing("BRI", prefix="bri", methodology="PER_PARCEL",
                               contract_price_cents=100000, contingency_cents=0,
                               venue="BRI Room", option="INSTALLMENTS", term_years=5)
        set_clock("2027-09-20T00:00:00Z")  # year-1 issue_date reached
        first = billing_run(ctx["district"]["id"])
        assert first["issued_count"] == 1
        assert first["newly_delinquent_count"] == 0

        second = billing_run(ctx["district"]["id"])
        assert second["issued_count"] == 0
        assert second["newly_delinquent_count"] == 0
        assert second["cured_count"] == 0
