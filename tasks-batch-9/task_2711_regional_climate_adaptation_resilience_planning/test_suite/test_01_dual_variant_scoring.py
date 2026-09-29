"""The two scoring variants that must not be reparameterizations of one another."""

from test_helpers import (
    assert_fields,
    assert_project_dimensions,
    assess,
    create_analysis,
    create_asset,
    create_asset_link,
    create_assessed_assessment,
    create_assessment,
    create_harbor,
    create_plan_cycle,
    create_published_profile,
    create_screened_project,
    rank_asset,
    read_analysis,
    read_assessment,
    read_project,
    reject_analysis,
)


class TestVulnerabilityMethodVariants:
    """One receptor, one projection, two algorithms, two different bands."""

    @staticmethod
    def _two_assessments():
        harbor = create_harbor()
        profile = create_published_profile(harbor["id"], exposure_index=0.80)
        asset = create_asset(harbor["id"])
        multiplicative = create_assessment(
            profile["id"],
            asset["id"],
            subject_type="INFRASTRUCTURE",
            sensitivity_score=0.60,
            adaptive_capacity_score=0.50,
            method="COMPOSITE_MULTIPLICATIVE",
            svi_overlay_applied=True,
        )
        additive = create_assessment(
            profile["id"],
            asset["id"],
            subject_type="INFRASTRUCTURE",
            sensitivity_score=0.60,
            adaptive_capacity_score=0.50,
            method="ADDITIVE_WEIGHTED",
            svi_overlay_applied=True,
        )
        return harbor, multiplicative, additive

    def test_multiplicative_and_additive_scores_diverge_into_different_bands(self):
        """Identical inputs score 0.30/MODERATE multiplicatively and 0.82/EXTREME additively.

        PRD 3.3 pins both algorithms: "Under `COMPOSITE_MULTIPLICATIVE`, the raw
        figure is the exposure term multiplied by the sensitivity term multiplied
        by the adaptive gap. Under `ADDITIVE_WEIGHTED`, the raw figure is the
        exposure term weighted at 0.40, plus the sensitivity term weighted at
        0.35, plus the adaptive gap weighted at 0.25."  It also fixes the band
        cutoffs: "`EXTREME` when the score is at least 0.75, `HIGH` when it is at
        least 0.50, `MODERATE` when it is at least 0.25, and `LOW` otherwise."

        Design: Difficulty/dual_variant_calc/vulnerability_score_multiplicative_vs_additive_diverges
        """
        harbor, multiplicative, additive = self._two_assessments()

        assert_fields(
            harbor,
            {"svi_tier": "HIGH", "disadvantaged_flag": True},
            "jurisdiction with svi_score 0.62",
        )

        scored_multiplicative = assess(multiplicative["id"])
        scored_additive = assess(additive["id"])

        assert_fields(
            scored_multiplicative,
            {"vulnerability_score": 0.30, "vulnerability_band": "MODERATE"},
            "COMPOSITE_MULTIPLICATIVE assessment",
        )
        assert_fields(
            scored_additive,
            {"vulnerability_score": 0.82, "vulnerability_band": "EXTREME"},
            "ADDITIVE_WEIGHTED assessment",
        )
        gap = round(
            float(scored_additive["vulnerability_score"])
            - float(scored_multiplicative["vulnerability_score"]),
            2,
        )
        assert gap == 0.52, (
            "the two variants must genuinely diverge on identical inputs; the gap "
            f"between the additive and multiplicative scores read {gap}"
        )
        assert (
            scored_additive["vulnerability_band"]
            != scored_multiplicative["vulnerability_band"]
        ), "identical inputs must be able to land in different vulnerability bands"

    def test_both_variants_record_the_same_assessed_profile_version(self):
        """Scoring either variant stamps the projection counter and moves the row to ASSESSED.

        PRD 3.3: "On success the row moves `DRAFT → ASSESSED` on its first pass,
        or `STALE → ASSESSED` when it is being refreshed after a republication;
        either way `assessed_at` is stamped with the logical clock instant,
        `assessed_profile_version` is set to the profile's current
        `published_version`, and the assessment's `version` increments by 1."

        Design: Difficulty/dual_variant_calc/vulnerability_score_multiplicative_vs_additive_diverges
        """
        _, multiplicative, additive = self._two_assessments()

        assess(multiplicative["id"])
        assess(additive["id"])

        for row, label in (
            (read_assessment(multiplicative["id"]), "COMPOSITE_MULTIPLICATIVE assessment"),
            (read_assessment(additive["id"]), "ADDITIVE_WEIGHTED assessment"),
        ):
            assert_fields(
                row,
                {"status": "ASSESSED", "assessed_profile_version": 1},
                label,
            )
            assert row["assessed_at"] is not None, (
                f"{label}.assessed_at must be stamped from the logical clock on assessment"
            )


class TestBenefitCostMethodVariants:
    """Discounted and annualized cases land on opposite sides of the grant floor."""

    @staticmethod
    def _levee_project_with_one_link():
        harbor = create_harbor()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        profile = create_published_profile(harbor["id"], exposure_index=0.80)
        asset = create_asset(harbor["id"])
        create_assessed_assessment(profile["id"], asset["id"], method="ADDITIVE_WEIGHTED")
        rank_asset(asset["id"])
        project = create_screened_project(
            cycle["id"],
            harbor["id"],
            name="Harbor Levee Raise",
            strategy_type="PROTECT",
            base_cost_cents=42000000,
            service_life_years=30,
            cobenefit_points=12,
            feasibility_score=0.70,
        )
        create_asset_link(
            project["id"],
            harbor["id"],
            asset["id"],
            3333333,
            benefit_reaches_disadvantaged=True,
        )
        return harbor, project

    def test_discounted_npv_falls_below_the_grant_floor(self):
        """A 30-year discounted case on 3333333 cents of annual benefit is not grant eligible.

        PRD 3.6: "Under **`DISCOUNTED_NPV`**, the server first computes an **annuity
        factor**: one, minus the quantity one plus the discount rate raised to the
        power of the negative horizon, all divided by the discount rate."  On the
        cost side, "`cost_measure_cents` is the capital amount plus the discounted
        operations-and-maintenance stream, where that stream is the capital amount
        multiplied by two percent multiplied by the annuity factor, rounded half up
        to whole cents."  Eligibility follows: "`grant_eligible` is true exactly
        when that **rounded** `bcr` is at least 1.0000."

        Design: Difficulty/dual_variant_calc/bca_discounted_npv_vs_annualized_equivalent_diverges
        """
        harbor, project = self._levee_project_with_one_link()

        assert_fields(
            project,
            {"total_program_cost_cents": 51273600},
            "screened PROTECT project",
        )

        npv = create_analysis(
            project["id"], harbor["id"], method="DISCOUNTED_NPV", discount_rate_bps=700
        )

        assert_fields(
            npv,
            {
                "benefit_measure_cents": 41363466,
                "cost_measure_cents": 63998724,
                "bcr": 0.6463,
                "grant_eligible": False,
            },
            "DISCOUNTED_NPV analysis",
        )

    def test_annualized_equivalent_clears_the_grant_floor_on_the_same_inputs(self):
        """The undiscounted case on the identical project and link is grant eligible.

        PRD 3.6: "Under **`ANNUALIZED_EQUIVALENT`**, no discounting happens at all.
        `benefit_measure_cents` is the exact integer sum of every link's
        `avoided_loss_annual_cents` — one undiscounted year of benefit.
        `cost_measure_cents` is the capital amount divided by the horizon in years
        and rounded half up to whole cents, plus the capital amount multiplied by
        two percent and rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/bca_discounted_npv_vs_annualized_equivalent_diverges
        """
        harbor, project = self._levee_project_with_one_link()

        annualized = create_analysis(
            project["id"],
            harbor["id"],
            method="ANNUALIZED_EQUIVALENT",
            discount_rate_bps=700,
        )

        assert_fields(
            annualized,
            {
                "benefit_measure_cents": 3333333,
                "cost_measure_cents": 2734592,
                "bcr": 1.2190,
                "grant_eligible": True,
            },
            "ANNUALIZED_EQUIVALENT analysis",
        )

    def test_the_two_variants_straddle_the_floor_on_one_project(self):
        """Rejecting the discounted case and preparing the annualized one shows the divergence.

        PRD 3.6: "The two variants are emphatically not reciprocals of one another
        and routinely land on opposite sides of the eligibility floor: the
        discounted form loads a whole horizon of discounted upkeep onto the cost
        while discounting the benefit stream, whereas the annualized form compares
        a single year against a single year."  Rejection is available regardless of
        the ratio: "A reviewer may reject a case whose ratio is perfectly healthy."

        Design: Difficulty/dual_variant_calc/bca_discounted_npv_vs_annualized_equivalent_diverges
        """
        harbor, project = self._levee_project_with_one_link()

        npv = create_analysis(
            project["id"], harbor["id"], method="DISCOUNTED_NPV", discount_rate_bps=700
        )
        reject_analysis(npv["id"])
        annualized = create_analysis(
            project["id"],
            harbor["id"],
            method="ANNUALIZED_EQUIVALENT",
            discount_rate_bps=700,
        )

        assert_fields(read_analysis(npv["id"]), {"status": "REJECTED"}, "discounted analysis")
        assert_fields(
            read_analysis(annualized["id"]), {"status": "DRAFT"}, "annualized analysis"
        )
        assert float(npv["bcr"]) < 1.0000 <= float(annualized["bcr"]), (
            "the discounted and annualized cases must straddle the 1.0000 grant "
            f"floor, got {npv['bcr']} and {annualized['bcr']}"
        )
        assert_project_dimensions(read_project(project["id"]), analysis="BCA_PENDING")
