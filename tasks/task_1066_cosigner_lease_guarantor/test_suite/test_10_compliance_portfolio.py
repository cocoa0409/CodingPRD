"""Compliance review segregation of duties and portfolio risk posture
(PRD §3.8, §2.7, §3.5)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_guarantee, create_portfolio, create_applicant, create_quoted_guarantee,
    open_compliance_review, make_compliance_officer_headers,
)


class TestComplianceSegregationOfDuties:
    def test_opener_cannot_clear_own_review(self, api):
        """PRD §3.8: "Both resolutions require that the acting `X-User-ID` differ from the
        review's `opened_by_user_id`; the opener may not close their own review, and a
        match is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/compliance_clear_by_opener_returns_403_sod
        """
        pf = create_portfolio(api, exposure_cap_cents=100_000_000)
        ap = create_applicant(api)
        g = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1", unit_id="U-SD2")
        review = open_compliance_review(api, g["id"], reason="KYC_MISMATCH", officer_id="co1")
        resp = api.clear_compliance_review(review["id"], {},
                                          make_compliance_officer_headers("co1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestPortfolioPosture:
    def test_recompute_sets_restricted_posture_in_warning_band(self, api):
        """PRD §2.7: "it reads `RESTRICTED` once `risk_weighted_exposure_cents` reaches or
        exceeds eighty percent of `exposure_cap_cents`, and `OPEN` otherwise."
        PRD §3.5: "The `risk_weighted_exposure_cents` is the weighted sum, over every
        guarantee in `ACTIVE` or `RENEWAL_PENDING`, of that guarantee's
        `remaining_coverage_cents` multiplied by the weight of its `risk_tier` (0.5 for
        `A`, 0.8 for `B`, 1.2 for `C`, 2.0 for `D`), with the half-up rounding to whole
        cents applied once, after the whole weighted sum."

        Design: Corner/calculations/portfolio_posture_restricted_when_weighted_exceeds_cap
        """
        ctx = setup_active_guarantee(
            api, portfolio_overrides={"exposure_cap_cents": 800000},
            applicant_overrides={"credit_score": 740, "annual_income_cents": 12_000_000,
                                 "monthly_obligations_cents": 200_000},
            guarantee_overrides={"monthly_rent_cents": 249_999, "coverage_months": 6,
                                 "term_months": 12})
        pf = validate_success(api.recompute_portfolio_risk(
            ctx["pf_id"], make_compliance_officer_headers("co1")))
        assert pf["risk_weighted_exposure_cents"] == 674997, \
            f"expected 674997, got {pf['risk_weighted_exposure_cents']}"
        assert pf["posture"] == "RESTRICTED", f"expected RESTRICTED, got {pf['posture']}"
