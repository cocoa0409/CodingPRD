"""Revenue estimation: the PTELL cap, per-fund tax-rate rounding, the
provisional vs certified state-aid variants, and recertification
(PRD §3.4)."""
from test_helpers import (
    ApiErrorId, assert_money, assert_rate, assert_revenue_estimate,
    get_success_data, validate_error, validate_paginated, validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_revenue_estimate_payload
from test_helpers.fixtures import (
    certify_projection, create_budget_version, setup_draft_budget,
)
from test_helpers.test_users import TEST_USERS

BM = TEST_USERS["business_manager_headers"]
AU = TEST_USERS["auditor_headers"]


class TestDualVariantStateAid:
    """The same estimate carries a PROVISIONAL variant (projected pupils,
    prior-year EAV) and, after recertification, a CERTIFIED variant
    (certified pupils, current-year EAV)."""

    def _setup_recertifiable(self, api):
        """Three projections (1200/800/1000) + estimate, all projections then
        certified with actuals 1250/780/1020. Returns (ctx, estimate)."""
        ctx = setup_draft_budget(
            pupils_by_band={"ELEMENTARY": 1200, "MIDDLE": 800, "HIGH": 1000},
            line_amounts=(1000,))
        certify_projection(ctx["projections"]["ELEMENTARY"]["id"], 1250)
        certify_projection(ctx["projections"]["MIDDLE"]["id"], 780)
        certify_projection(ctx["projections"]["HIGH"]["id"], 1020)
        return ctx, ctx["re"]

    def test_provisional_variant_uses_projected_pupils_and_prior_eav(
            self, api):
        """PRD §3.4: "At creation the estimate is the provisional variant.
        State aid is the greater of zero and the difference between the
        foundation amount — 7,600 per weighted pupil, multiplied by the summed
        `weighted_pupils_projected` over every enrollment projection of the
        fiscal year — and 2.3 percent of the prior-year EAV; the `eav_basis`
        field reads `PRIOR`".

        Design: Difficulty/dual_variant_calc/state_aid_provisional_vs_certified_revenue_estimate
        """
        ctx = setup_draft_budget(
            pupils_by_band={"ELEMENTARY": 1200, "MIDDLE": 800, "HIGH": 1000},
            line_amounts=(1000,))
        est = validate_success(
            api.list_revenue_estimates(ctx["bv"]["id"], AU), 200)[0]
        assert_revenue_estimate(est)
        assert est["status"] == "PROVISIONAL"
        assert est["eav_basis"] == "PRIOR"
        # weighted pupils: 1200*1.00 + 800*1.05 + 1000*1.15 = 3190
        # state aid: 7600*3190 - 0.023*480,000,000 = 13,204,000.00
        assert_money(est["state_aid"], 13204000.00, "provisional state_aid")
        assert_rate(est["operating_rate"], 1.7708, "provisional operating_rate")
        assert_rate(est["debt_service_rate"], 0.2500,
                    "provisional debt_service_rate")
        assert_rate(est["total_tax_rate"], 2.0208, "provisional total_tax_rate")
        # total_revenue = 13,204,000 + 9,700,000 + 500,000
        assert_money(est["total_revenue"], 23404000.00,
                     "provisional total_revenue")

    def test_recertification_recomputes_and_retains_provisional(self, api):
        """PRD §3.4: "Recertification freezes the current provisional figures
        into `state_aid_provisional` and `total_revenue_provisional`, then
        recomputes the authoritative fields on the certified variant: state
        aid now uses the summed `weighted_pupils_certified` over the year's
        projections against the current-year EAV, `eav_basis` flips to
        `CURRENT`, the per-fund rates and `total_tax_rate` are restruck on
        that basis" and "The estimate moves `PROVISIONAL` → `RECERTIFIED` with
        its `version` incremented."

        Design: Difficulty/dual_variant_calc/state_aid_provisional_vs_certified_revenue_estimate
        """
        ctx, est = self._setup_recertifiable(api)
        rec = validate_success(
            api.recertify_revenue_estimate(est["id"], BM), 200)
        assert rec["status"] == "RECERTIFIED"
        assert rec["eav_basis"] == "CURRENT"
        # certified weighted pupils: 1250*1.00 + 780*1.05 + 1020*1.15 = 3242
        # state aid: 7600*3242 - 0.023*500,000,000 = 13,139,200.00
        assert_money(rec["state_aid"], 13139200.00, "certified state_aid")
        assert_rate(rec["operating_rate"], 1.7000, "certified operating_rate")
        assert_rate(rec["debt_service_rate"], 0.2400,
                    "certified debt_service_rate")
        assert_rate(rec["total_tax_rate"], 1.9400, "certified total_tax_rate")
        assert_money(rec["total_revenue"], 23339200.00,
                     "certified total_revenue")
        # The provisional variant is retained alongside for comparison.
        assert_money(rec["state_aid_provisional"], 13204000.00,
                     "state_aid_provisional retained")
        assert_money(rec["total_revenue_provisional"], 23404000.00,
                     "total_revenue_provisional retained")
        # The variants diverge by exactly 64,800.00 of state aid.
        assert_money(rec["state_aid"] - rec["state_aid_provisional"],
                     -64800.00, "variant divergence")


class TestPerFundRoundingOrder:
    def test_per_fund_rates_rounded_before_summation(self, api):
        """PRD §2.7: "Tax rates round half-up to 4 decimal places, per fund,
        before any summation: the district computes the operating rate and the
        debt-service rate independently, rounds each one, and only then forms
        their sum — the sum itself is never re-rounded." PRD §3.4:
        "`total_tax_rate` is the exact sum of the two already-rounded per-fund
        rates and is never re-rounded; striking a single rate from the summed
        levies is not a permitted equivalent."

        Design: Difficulty/combinatorial_formula/tax_rate_per_fund_rounding_then_sum
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 100},
                                 line_amounts=(1000,),
                                 with_revenue_estimate=False)
        est = get_success_data(api.create_revenue_estimate(
            ctx["bv"]["id"],
            create_revenue_estimate_payload(operating_levy_request=5925840,
                                            debt_service_levy=2400240,
                                            other_revenue=0, cpi_rate=0.034),
            BM), 201)
        # Unrounded 1.23455 -> 1.2346 and 0.50005 -> 0.5001 (half-up, 4dp).
        assert_rate(est["operating_rate"], 1.2346, "operating_rate")
        assert_rate(est["debt_service_rate"], 0.5001, "debt_service_rate")
        # Sum of the ROUNDED rates: 1.2346 + 0.5001 = 1.7347. The forbidden
        # order (sum levies 8,326,080 then round) would yield 1.7346.
        assert_rate(est["total_tax_rate"], 1.7347, "total_tax_rate")

    def test_state_aid_floors_at_zero(self, api):
        """PRD §3.4: "State aid is the greater of zero and the difference
        between the foundation amount — 7,600 per weighted pupil, multiplied
        by the summed `weighted_pupils_projected` over every enrollment
        projection of the fiscal year — and 2.3 percent of the prior-year
        EAV" and "Fifth, `total_levy` is the `capped_operating_levy` plus the
        `debt_service_levy`, which sits outside the PTELL cap."

        Design: Difficulty/combinatorial_formula/tax_rate_per_fund_rounding_then_sum
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 100},
                                 line_amounts=(1000,),
                                 with_revenue_estimate=False)
        est = get_success_data(api.create_revenue_estimate(
            ctx["bv"]["id"],
            create_revenue_estimate_payload(operating_levy_request=5925840,
                                            debt_service_levy=2400240,
                                            other_revenue=0, cpi_rate=0.034),
            BM), 201)
        # 7600*100 - 0.023*480,000,000 = -10,280,000 -> floored at zero.
        assert_money(est["state_aid"], 0.00, "state_aid zero floor")
        # PTELL cap 9,306,000 does not bind the 5,925,840 request.
        assert_money(est["capped_operating_levy"], 5925840.00,
                     "capped_operating_levy")
        assert_money(est["total_levy"], 8326080.00, "total_levy")
        assert_money(est["total_revenue"], 8326080.00, "total_revenue")


class TestPtellCapOrder:
    def test_ptell_cap_binds_before_rate_cap_check(self, api):
        """PRD §3.4: "Third, `capped_operating_levy` is set to the lesser of
        the raw request and that cap. Fourth, the operating rate is computed
        from the capped levy — never from the raw request — by dividing the
        capped levy by the applicable EAV basis, multiplying by 100, and
        rounding half-up to four decimal places; if that rounded rate exceeds
        1.8400, the estimate is rejected outright with
        `ERR_TAX_RATE_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/ptell_cap_binds_before_rate_cap_check
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 100},
                                 line_amounts=(1000,),
                                 with_revenue_estimate=False,
                                 fy_overrides={"prior_year_extension": 8000000})
        # PTELL cap: 8,000,000 * (1 + 0.034) = 8,272,000 binds the 9,000,000
        # request. The RAW rate 1.8750 would breach 1.8400; the capped rate
        # 1.7233 does not — proving cap-then-rate order.
        est = get_success_data(api.create_revenue_estimate(
            ctx["bv"]["id"],
            create_revenue_estimate_payload(operating_levy_request=9000000,
                                            debt_service_levy=1200000,
                                            other_revenue=0, cpi_rate=0.034),
            BM), 201)
        assert_money(est["capped_operating_levy"], 8272000.00,
                     "capped_operating_levy")
        assert_rate(est["operating_rate"], 1.7233, "operating_rate")

    def test_debt_service_levy_is_ptell_exempt(self, api):
        """PRD §3.4: "Fifth, `total_levy` is the `capped_operating_levy` plus
        the `debt_service_levy`, which sits outside the PTELL cap."

        Design: Difficulty/combinatorial_formula/ptell_cap_binds_before_rate_cap_check
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 100},
                                 line_amounts=(1000,),
                                 with_revenue_estimate=False,
                                 fy_overrides={"prior_year_extension": 8000000})
        est = get_success_data(api.create_revenue_estimate(
            ctx["bv"]["id"],
            create_revenue_estimate_payload(operating_levy_request=9000000,
                                            debt_service_levy=1200000,
                                            other_revenue=0, cpi_rate=0.034),
            BM), 201)
        # Debt service added after the cap: 8,272,000 + 1,200,000.
        assert_money(est["total_levy"], 9472000.00, "total_levy")
        # 1.7233 + 0.2500 (debt-service rate on prior EAV) = 1.9733.
        assert_rate(est["debt_service_rate"], 0.2500, "debt_service_rate")
        assert_rate(est["total_tax_rate"], 1.9733, "total_tax_rate")


class TestEstimateConstraints:
    def test_second_revenue_estimate_rejected(self, api):
        """PRD §3.4: "A `BusinessManager` attaches a **revenue estimate** to a
        budget version — at most one per version, with a second attempt
        failing as `ERR_REVENUE_ESTIMATE_EXISTS`".

        Design: Corner/validations/second_revenue_estimate_rejected
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 1200})
        resp = api.create_revenue_estimate(
            ctx["bv"]["id"],
            create_revenue_estimate_payload(operating_levy_request=1000000,
                                            debt_service_levy=0,
                                            other_revenue=0, cpi_rate=0.02),
            BM)
        validate_error(resp, ApiErrorId.ERR_REVENUE_ESTIMATE_EXISTS, 409)

    def test_recertify_with_uncertified_projection_rejected(self, api):
        """PRD §3.4: "Once every enrollment projection of the fiscal year has
        been certified, the `BusinessManager` may **recertify** the estimate;
        an attempt while any projection remains uncertified fails with
        `ERR_PROJECTIONS_NOT_ALL_CERTIFIED`."

        Design: Corner/validations/recertify_with_uncertified_projection_rejected
        """
        ctx = setup_draft_budget(
            pupils_by_band={"ELEMENTARY": 1200, "HIGH": 1000})
        certify_projection(ctx["projections"]["ELEMENTARY"]["id"], 1250)
        # HIGH remains PROVISIONAL.
        resp = api.recertify_revenue_estimate(ctx["re"]["id"], BM)
        validate_error(resp, ApiErrorId.ERR_PROJECTIONS_NOT_ALL_CERTIFIED, 409)
        est = validate_success(
            api.list_revenue_estimates(ctx["bv"]["id"], AU), 200)[0]
        assert est["status"] == "PROVISIONAL"
        assert est["eav_basis"] == "PRIOR"

    def test_revenue_estimate_computed_read_matches_formula(self, api):
        """PRD §3.4: "`total_revenue` closes the estimate as `state_aid` plus
        `total_levy` plus `other_revenue`, rounded half-up to two decimal
        places." and "Third, `capped_operating_levy` is set to the lesser of
        the raw request and that cap."

        Design: Corner/endpoints/revenue_estimate_computed_read_matches_formula
        """
        ctx = setup_draft_budget(
            pupils_by_band={"ELEMENTARY": 1200, "MIDDLE": 800, "HIGH": 1000})
        listing = validate_success(
            api.list_revenue_estimates(ctx["bv"]["id"], AU), 200)
        assert len(listing) == 1
        est = listing[0]
        assert_revenue_estimate(est)
        # Request 8,500,000 below the PTELL cap 9,306,000 passes through.
        assert_money(est["capped_operating_levy"], 8500000.00,
                     "capped_operating_levy")
        assert_money(est["total_levy"], 9700000.00, "total_levy")
        assert_money(est["state_aid"], 13204000.00, "state_aid")
        assert_money(est["total_revenue"], 23404000.00, "total_revenue")

    def test_ptell_cpi_capped_at_five_percent(self, api):
        """PRD §3.4: "Second, the cap is formed as the fiscal year's
        `prior_year_extension` grown by one plus the lesser of `cpi_rate` and
        5 percent."

        Design: Corner/calculations/ptell_cpi_capped_at_five_percent
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 100},
                                 with_revenue_estimate=False,
                                 fy_overrides={"prior_year_extension": 8000000})
        # cpi 0.07 is clamped to 0.05: cap = 8,000,000 * 1.05 = 8,400,000.
        est = get_success_data(api.create_revenue_estimate(
            ctx["bv"]["id"],
            create_revenue_estimate_payload(operating_levy_request=8500000,
                                            debt_service_levy=0,
                                            other_revenue=0, cpi_rate=0.07),
            BM), 201)
        assert_money(est["capped_operating_levy"], 8400000.00,
                     "capped_operating_levy")
        assert_rate(est["operating_rate"], 1.7500, "operating_rate")

    def test_operating_rate_cap_exact_boundary(self, api):
        """PRD §3.4: "if that rounded rate exceeds 1.8400, the estimate is
        rejected outright with `ERR_TAX_RATE_CAP_EXCEEDED`" — the cap binds on
        the rounded rate, so exactly 1.8400 passes and 1.8750 fails.

        Design: Corner/calculations/operating_rate_cap_exact_boundary
        """
        ctx = setup_draft_budget(pupils_by_band={"ELEMENTARY": 100},
                                 with_revenue_estimate=False)
        bv1 = ctx["bv"]
        bv2 = create_budget_version(ctx["fy"]["id"])
        # 8,832,000 / 480,000,000 * 100 = 1.8400 exactly -> allowed.
        est = get_success_data(api.create_revenue_estimate(
            bv1["id"],
            create_revenue_estimate_payload(operating_levy_request=8832000,
                                            debt_service_levy=0,
                                            other_revenue=0, cpi_rate=0.034),
            BM), 201)
        assert_rate(est["operating_rate"], 1.8400, "operating_rate at cap")
        # 9,000,000 / 480,000,000 * 100 = 1.8750 > 1.8400 -> rejected.
        resp = api.create_revenue_estimate(
            bv2["id"],
            create_revenue_estimate_payload(operating_levy_request=9000000,
                                            debt_service_levy=0,
                                            other_revenue=0, cpi_rate=0.034),
            BM)
        validate_error(resp, ApiErrorId.ERR_TAX_RATE_CAP_EXCEEDED, 422)
        # The rejection is atomic: no estimate persists on v2.
        listing, meta = validate_paginated(
            api.list_revenue_estimates(bv2["id"], AU))
        assert listing == []
        assert meta["total_count"] == 0
