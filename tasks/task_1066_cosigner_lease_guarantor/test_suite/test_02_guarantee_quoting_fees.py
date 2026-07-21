"""Guarantee quoting, fee pricing (provisional vs final), and version/read semantics
(PRD §3.2, §3.4, §2.4)."""
from test_helpers import (
    validate_success, get_success_data, assert_guarantee,
    setup_quoted_guarantee, create_portfolio, create_verified_applicant,
    create_quoted_guarantee, make_underwriter_headers,
)


class TestProvisionalVsFinalFee:
    """Dual-variant fee: fixed provisional tier C vs verified final tier A."""

    def test_provisional_fee_uses_fixed_tier_C(self, api):
        """PRD §3.2: "because verification has not yet happened, the provisional fee
        always uses the fixed provisional tier `C`, that is, the tier-`C` rate of 0.12,
        regardless of the applicant."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_diverge_on_guarantee
        """
        pf = create_portfolio(api, exposure_cap_cents=100_000_000)
        ap = create_verified_applicant(api, credit_score=740, annual_income_cents=12_000_000,
                                       monthly_obligations_cents=200_000)
        g = validate_success(api.create_guarantee(
            {"portfolio_id": pf["id"], "applicant_id": ap["id"], "unit_id": "U-DV1",
             "monthly_rent_cents": 249_999, "coverage_months": 6, "term_months": 12,
             "lease_start_date": "2026-08-01T00:00:00Z",
             "lease_end_date": "2027-08-01T00:00:00Z"},
            make_underwriter_headers("uw1")), expected_status=201)
        assert_guarantee(g)
        assert g["provisional_fee_cents"] == 161999, \
            f"expected provisional 161999, got {g['provisional_fee_cents']}"

    def test_final_fee_uses_verified_tier_and_differs_from_provisional(self, api):
        """PRD §3.4: "The final fee therefore differs from the provisional fee whenever
        the verified tier is not `C`."
        PRD §3.4: "the base rate is now the verified applicant tier's rate rather than
        the provisional tier-`C` rate."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_diverge_on_guarantee
        """
        ctx = setup_quoted_guarantee(
            api, portfolio_overrides={"exposure_cap_cents": 100_000_000},
            applicant_overrides={"credit_score": 740, "annual_income_cents": 12_000_000,
                                 "monthly_obligations_cents": 200_000},
            guarantee_overrides={"monthly_rent_cents": 249_999, "coverage_months": 6,
                                 "term_months": 12})
        provisional = ctx["guarantee"]["provisional_fee_cents"]
        approved = validate_success(api.approve_guarantee(ctx["g_id"],
                                                          make_underwriter_headers("uw1")))
        assert approved["final_fee_cents"] == 67500, \
            f"expected final 67500, got {approved['final_fee_cents']}"
        assert approved["final_fee_cents"] != provisional, \
            "final fee must differ from provisional for a non-C tier"


class TestFeeFloorClamp:
    """Raw fee below the 15000 floor is clamped up."""

    def test_final_fee_clamped_up_to_floor(self, api):
        """PRD §3.4: "the fee machinery of Section 3.2 — base rate times
        `total_coverage_cents` times the term factor of `term_months` over twelve,
        rounded half up once and clamped between 15000 and 500000 cents".

        Design: Difficulty/combinatorial_formula/fee_min_floor_clamp_tier_and_term
        """
        ctx = setup_quoted_guarantee(
            api, portfolio_overrides={"exposure_cap_cents": 100_000_000},
            applicant_overrides={"credit_score": 740, "annual_income_cents": 6_000_000,
                                 "monthly_obligations_cents": 100_000},
            guarantee_overrides={"monthly_rent_cents": 100_000, "coverage_months": 1,
                                 "term_months": 12})
        approved = validate_success(api.approve_guarantee(ctx["g_id"],
                                                          make_underwriter_headers("uw1")))
        assert approved["final_fee_cents"] == 15000, \
            f"expected floor 15000, got {approved['final_fee_cents']}"

    def test_provisional_fee_clamped_up_to_floor(self, api):
        """PRD §3.2: "Finally clamp the rounded figure into the fee band: never less
        than 15000 cents and never more than 500000 cents."

        Design: Difficulty/combinatorial_formula/fee_min_floor_clamp_tier_and_term
        """
        pf = create_portfolio(api, exposure_cap_cents=100_000_000)
        ap = create_verified_applicant(api, credit_score=740, annual_income_cents=6_000_000,
                                       monthly_obligations_cents=100_000)
        g = create_quoted_guarantee(api, pf["id"], ap["id"], uw_id="uw1",
                                    monthly_rent_cents=100_000, coverage_months=1,
                                    term_months=12)
        assert g["provisional_fee_cents"] == 15000, \
            f"expected provisional floor 15000, got {g['provisional_fee_cents']}"


class TestFeeCeilingClamp:
    def test_final_fee_clamped_down_to_ceiling_tier_D(self, api):
        """PRD §3.4: "the fee machinery of Section 3.2 — base rate times
        `total_coverage_cents` times the term factor of `term_months` over twelve,
        rounded half up once and clamped between 15000 and 500000 cents".

        Design: Corner/calculations/fee_max_cap_clamp_tier_D
        """
        ctx = setup_quoted_guarantee(
            api, portfolio_overrides={"exposure_cap_cents": 100_000_000},
            applicant_overrides={"credit_score": 600, "annual_income_cents": 24_000_000,
                                 "monthly_obligations_cents": 1_200_000,
                                 "employment_type": "SELF_EMPLOYED"},
            guarantee_overrides={"monthly_rent_cents": 400_000, "coverage_months": 10,
                                 "term_months": 12})
        assert ctx["applicant"]["risk_tier"] == "D"
        approved = validate_success(api.approve_guarantee(ctx["g_id"],
                                                          make_underwriter_headers("uw1")))
        assert approved["final_fee_cents"] == 500000, \
            f"expected ceiling 500000, got {approved['final_fee_cents']}"


class TestGuaranteeVersionAndReads:
    def test_created_guarantee_version_is_one(self, api):
        """PRD §2.4: "an integer `version` that starts at 1 and increments by one on
        each mutation."

        Design: Corner/cross_cutting_complexity_layers/guarantee_version_increments_on_mutation
        """
        ctx = setup_quoted_guarantee(api)
        assert ctx["guarantee"]["version"] == 1, \
            f"expected created version 1, got {ctx['guarantee']['version']}"

    def test_version_increments_after_approve(self, api):
        """PRD §2.4: "an integer `version` that starts at 1 and increments by one on
        each mutation."

        Design: Corner/cross_cutting_complexity_layers/guarantee_version_increments_on_mutation
        """
        ctx = setup_quoted_guarantee(api)
        approved = validate_success(api.approve_guarantee(ctx["g_id"],
                                                          make_underwriter_headers("uw1")))
        assert approved["version"] > 1, \
            f"expected version > 1 after approve, got {approved['version']}"

    def test_get_after_approve_reflects_status_and_final_fee(self, api):
        """PRD §3.4: "Approving a guarantee advances it from `QUOTED` to `APPROVED`".
        PRD §3.4: "The final fee therefore differs from the provisional fee whenever
        the verified tier is not `C`."

        Design: Corner/consistency_model/immediate_read_after_write_reflects_state
        """
        ctx = setup_quoted_guarantee(
            api, applicant_overrides={"credit_score": 740, "annual_income_cents": 12_000_000,
                                      "monthly_obligations_cents": 200_000},
            guarantee_overrides={"monthly_rent_cents": 249_999, "coverage_months": 6,
                                 "term_months": 12})
        get_success_data(api.approve_guarantee(ctx["g_id"], make_underwriter_headers("uw1")))
        fetched = validate_success(api.get_guarantee(ctx["g_id"],
                                                     make_underwriter_headers("uw1")))
        assert fetched["status"] == "APPROVED"
        assert fetched["final_fee_cents"] == 67500
