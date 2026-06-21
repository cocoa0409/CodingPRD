"""Dual-variant calculations: replacement-cost (COMPONENT vs SQFT_BLEND) and
wildfire score (PROVISIONAL vs FINAL). Queue A — rule dual_variant_calc.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    make_inspector_headers,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestReplacementCostVariant:
    def test_component_commit_yields_274200_and_variant(self, api):
        """PRD §3.1: "The committed replacement cost is the structure cost plus the
        age-adjusted roof figure, rounded half up to two decimal places, and the
        variant recorded is `COMPONENT`."

        Design: Difficulty/dual_variant_calc/replacement_cost_component_vs_sqft_blend
        """
        prop = fx.create_property(
            street_address="1 Pine St", state_code="CA", year_built=2005,
            square_footage=2000, construction_type="FRAME", roof_age_years=5, stories=1,
        )
        data = validate_success(
            api.estimate_replacement_cost(prop["id"], f.estimate_payload("COMPONENT"), AGENT)
        )
        assert data["replacement_cost"] == 274200.00, (
            f"Expected COMPONENT replacement_cost 274200.00, got {data['replacement_cost']}"
        )
        assert data["estimate_variant"] == "COMPONENT"

    def test_sqft_blend_diverges_from_component(self, api):
        """PRD §3.1: "The committed replacement cost is that blended rate multiplied
        by the square footage and by the story factor, rounded half up to two decimal
        places, and the variant recorded is `SQFT_BLEND`. Because the blend folds the
        roof in without any age depreciation, the same property generally yields a
        different dollar value under each method."

        Design: Difficulty/dual_variant_calc/replacement_cost_component_vs_sqft_blend
        """
        prop = fx.create_property(
            street_address="1 Pine St", state_code="CA", year_built=2005,
            square_footage=2000, construction_type="FRAME", roof_age_years=5, stories=1,
        )
        comp = validate_success(
            api.estimate_replacement_cost(prop["id"], f.estimate_payload("COMPONENT"), AGENT)
        )
        blend = validate_success(
            api.estimate_replacement_cost(prop["id"], f.estimate_payload("SQFT_BLEND"), AGENT)
        )
        assert comp["replacement_cost"] == 274200.00
        assert blend["replacement_cost"] == 283200.00, (
            f"Expected SQFT_BLEND replacement_cost 283200.00, got {blend['replacement_cost']}"
        )
        assert blend["estimate_variant"] == "SQFT_BLEND"
        assert blend["replacement_cost"] != comp["replacement_cost"], (
            "The two variants must diverge for the same property"
        )


class TestWildfireScoreVariant:
    def test_provisional_score_before_inspection(self, api):
        """PRD §3.2: "the provisional `wildfire_score` is that raw figure rounded half
        up to the nearest integer and then clamped to the range 0 through 100. The
        provisional score carries no mitigation credit, which is why it runs higher
        and reflects the pre-inspection risk view."

        Design: Difficulty/dual_variant_calc/wildfire_score_provisional_vs_final
        """
        prop = fx.create_property(
            street_address="2 Oak St", state_code="CA", year_built=2010,
            square_footage=1800, construction_type="FRAME", roof_age_years=3, stories=1,
        )
        ra = validate_success(
            api.create_risk_assessment(
                f.create_risk_assessment_payload(
                    prop["id"], wildfire_fuel_density=90, slope_grade_pct=80,
                    defensible_space_ft=50, flood_zone="X", distance_to_coast_mi=60,
                ),
                UW,
            ),
            201,
        )
        assert ra["wildfire_score"] == 88, f"Expected provisional 88, got {ra['wildfire_score']}"
        assert ra["score_stage"] == "PROVISIONAL"

    def test_final_score_after_inspection_pass_subtracts_credit(self, api):
        """PRD §3.2: "the score is recomputed under the final variant: the same
        rounded raw figure, less a verified-mitigation credit of 12 points, then
        clamped to the range 0 through 100."
        PRD §3.3: "The transition to `PASSED` is the event that finalizes the
        property's wildfire score — it flips the related risk assessment's
        `score_stage` to `FINAL` and recomputes `wildfire_score` under the final,
        mitigation-credited variant."

        Design: Difficulty/dual_variant_calc/wildfire_score_provisional_vs_final
        """
        inspector = fx.create_inspector(buffer_minutes=60)
        prop = fx.create_property(
            street_address="2 Oak St", state_code="CA", year_built=2010,
            square_footage=1800, construction_type="FRAME", roof_age_years=3, stories=1,
        )
        ra = fx.create_risk_assessment(
            prop["id"], wildfire_fuel_density=90, slope_grade_pct=80,
            defensible_space_ft=50, flood_zone="X", distance_to_coast_mi=60,
        )
        assert ra["wildfire_score"] == 88 and ra["score_stage"] == "PROVISIONAL"

        insp = fx.schedule_inspection(prop["id"], inspector["id"], 1750000000, 1750007200)
        validate_success(
            api.complete_inspection(
                insp["id"], f.complete_inspection_payload(True, True, True, True),
                make_inspector_headers(inspector["id"]),
            )
        )
        ra_after = validate_success(api.get_risk_assessment(ra["id"], UW))
        assert ra_after["score_stage"] == "FINAL"
        assert ra_after["wildfire_score"] == 76, (
            f"Expected FINAL 76 (88 - 12 credit), got {ra_after['wildfire_score']}"
        )
        assert ra_after["wildfire_score"] != 88
