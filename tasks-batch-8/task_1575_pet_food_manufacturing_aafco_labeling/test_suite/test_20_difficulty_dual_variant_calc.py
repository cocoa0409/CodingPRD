"""Difficulty: dual-variant calculations — ME energetics and complaint risk
scoring each have two PRD-pinned variants (PRD §3.3, §3.8)."""
import pytest

from test_helpers import (
    create_complaint,
    nutrient_profile_payload,
    setup_draft_formula,
    validate_success,
)


class TestMeCalculationFormulationVsLabVariant:
    def test_me_formulation_calc_variant_value(self, api, formulation_scientist_headers):
        """PRD §3.3: "Gross energy per 100 grams is the crude protein percentage
        multiplied by 5.7, plus the crude fat percentage multiplied by 9.4, plus
        the carbohydrate percentage multiplied by 4.1 — where the carbohydrate
        percentage is whatever remains of 100 after subtracting the protein, fat,
        fiber, and moisture percentages and an assumed ash content of 7.0 percent.
        Percent digestibility is 87.8 minus the product of three terms: 0.88, the
        fiber percentage, and the ratio of 100 to the larger of two values (100
        minus the moisture percentage, or 1.0). Metabolizable energy in kcal per
        kilogram is the gross energy per 100 grams multiplied by the digestibility
        expressed as a fraction, then multiplied by 10, rounded half up to 1
        decimal place."

        Design: Difficulty/dual_variant_calc/me_calculation_formulation_vs_lab_variant
        """
        ctx = setup_draft_formula()  # DOG / ADULT_MAINTENANCE / FORMULATION
        profile = validate_success(
            api.create_nutrient_profile(
                ctx["formula"]["id"],
                nutrient_profile_payload(
                    profile_basis="FORMULATION_CALC",
                    crude_protein_min_pct=26.0, crude_fat_min_pct=9.0,
                    crude_fiber_max_pct=3.0, moisture_max_pct=10.0,
                ),
                formulation_scientist_headers,
            ),
            expected_status=201,
        )
        # carb 45, GE 417.3, digestibility 84.8667 -> ME 3541.5
        assert profile["metabolizable_energy_kcal_per_kg"] == pytest.approx(3541.5, abs=0.05)

    def test_me_lab_analysis_variant_diverges(self, api, formulation_scientist_headers):
        """PRD §3.3: "When the profile's basis is `LAB_ANALYSIS`, the fiber
        coefficient inside the digestibility term is halved — 0.44 instead of
        0.88 — reflecting measured energy density, so identical macro inputs
        yield a different energy figure than the `FORMULATION_CALC` variant."

        Design: Difficulty/dual_variant_calc/me_calculation_formulation_vs_lab_variant
        """
        ctx = setup_draft_formula()
        formulation = validate_success(
            api.create_nutrient_profile(
                ctx["formula"]["id"],
                nutrient_profile_payload(
                    profile_basis="FORMULATION_CALC",
                    crude_protein_min_pct=26.0, crude_fat_min_pct=9.0,
                    crude_fiber_max_pct=3.0, moisture_max_pct=10.0,
                ),
                formulation_scientist_headers,
            ),
            expected_status=201,
        )
        lab = validate_success(
            api.create_nutrient_profile(
                ctx["formula"]["id"],
                nutrient_profile_payload(
                    profile_basis="LAB_ANALYSIS",
                    crude_protein_min_pct=26.0, crude_fat_min_pct=9.0,
                    crude_fiber_max_pct=3.0, moisture_max_pct=10.0,
                ),
                formulation_scientist_headers,
            ),
            expected_status=201,
        )
        # digestibility 86.3333 -> ME 3602.7; the halved coefficient diverges.
        assert lab["metabolizable_energy_kcal_per_kg"] == pytest.approx(3602.7, abs=0.05)
        assert (
            formulation["metabolizable_energy_kcal_per_kg"]
            != lab["metabolizable_energy_kcal_per_kg"]
        )


class TestComplaintRiskScoreProvisionalVsFinal:
    def test_provisional_score_omits_adverse_bonus(self, api, quality_analyst_headers):
        """PRD §3.8: "Intake lands the case in `INTAKE` and computes a provisional
        `triage_score`."
        PRD §3.8: "The provisional score at intake omits the adverse-event bonus
        until the flag is confirmed; the final score at triage includes it
        whenever `adverse_event_flag` is true, so an identical severity–category
        pair scores lower provisionally than finally when an adverse event is
        confirmed."

        Design: Difficulty/dual_variant_calc/complaint_risk_score_provisional_vs_final
        """
        ctx = setup_draft_formula()
        case = create_complaint(
            ctx["brand"]["id"], ctx["formula"]["id"],
            severity="SERIOUS", category="ILLNESS", adverse_event_flag=False,
        )
        assert case["status"] == "INTAKE"
        # SERIOUS 20 + ILLNESS 15, bonus omitted provisionally.
        assert case["triage_score"] == pytest.approx(35.0, abs=0.005)

    def test_final_score_includes_confirmed_adverse_bonus(self, api, quality_analyst_headers):
        """PRD §3.8: "Severity contributes 5 points for `MINOR`, 20 for `SERIOUS`,
        45 for `LIFE_THREATENING`, and 60 for `DEATH`. Category contributes 2 for
        `PALATABILITY`, 3 for `PACKAGING`, 8 for `LABEL_DEFECT`, 12 for
        `FOREIGN_MATERIAL`, and 15 for `ILLNESS`. A confirmed adverse event adds
        a further 10 points."
        PRD §3.8: "ordinarily the case moves from `INTAKE` to `TRIAGED`, but when
        the final score reaches 60.0 or higher the case auto-escalates directly
        to `ESCALATED_RECALL` instead"

        Design: Difficulty/dual_variant_calc/complaint_risk_score_provisional_vs_final
        """
        ctx = setup_draft_formula()
        case = create_complaint(
            ctx["brand"]["id"], ctx["formula"]["id"],
            severity="SERIOUS", category="ILLNESS", adverse_event_flag=False,
        )
        triaged = validate_success(
            api.triage_complaint(
                case["id"], {"confirm_adverse_event_flag": True}, quality_analyst_headers
            )
        )
        # 20 + 15 + 10 = 45.0; below the 60.0 fork, so the case lands TRIAGED.
        assert triaged["triage_score"] == pytest.approx(45.0, abs=0.005)
        assert triaged["status"] == "TRIAGED"
