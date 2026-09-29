"""Two calculations that each exist in two variants over the same inputs.

The clean seed unit is booked twice for one physical harvest: once as a provisional
estimate at intake and once as a measured figure after bagging. Field eligibility is
likewise answered twice, by a strict variant and by a decay-weighted variant.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    GOLDEN_FIGURES,
    TEST_DEFAULTS,
    assert_eligibility_assessment,
    assert_harvest_event,
    assert_lot_mass_conserved,
    assert_seed_lot,
    bagged_lot_state,
    create_eligibility_assessment_payload,
    get_success_data,
    harvested_lot_state,
    make_field_history_record,
    make_grower,
    make_production_field,
    make_program_admin_headers,
    make_variety,
    validate_success,
)


class TestCleanUnitVariantDivergence:
    def test_provisional_basis_books_intake_estimate_on_the_harvest_event(self, api):
        """Intake books a moisture dockage, a provisional clean mass and provisional units.

        PRD: "First, a book moisture dockage percentage is derived as the intake moisture
        percentage minus a 12.0 percent base moisture, multiplied by a shrink factor of 1.5,
        and floored at zero so that seed at or below base moisture takes no dockage; that
        value is stored on the harvest event as `moisture_dockage_pct`."

        Design: Difficulty/dual_variant_calc/clean_unit_variant_divergence_provisional_vs_final
        """
        state = harvested_lot_state(api)
        event = state["harvest_event"]
        assert_harvest_event(event)

        assert event["moisture_pct"] == pytest.approx(TEST_DEFAULTS["MOISTURE_PCT"], abs=0.01)
        assert event["moisture_dockage_pct"] == pytest.approx(
            GOLDEN_FIGURES["MOISTURE_DOCKAGE_PCT"], abs=0.01
        )
        assert event["provisional_clean_kg"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_KG"], abs=0.001
        )
        assert event["provisional_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )

        lot = state["seed_lot"]
        assert_seed_lot(lot)
        assert lot["provisional_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )
        assert lot["final_clean_units"] is None
        assert lot["conditioning_status"] == "RAW"
        assert lot["certification_status"] == "UNSAMPLED"

        contract = state["contract"]
        assert contract["provisional_clean_units_total"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )

    def test_final_bagged_basis_diverges_from_the_provisional_figure(self, api):
        """The measured bagging output produces a final figure the intake estimate never saw.

        PRD: "Because it measures rather than estimates, a plant that performed better or
        worse than the variety's book shrink will produce a final figure that diverges from
        the provisional figure computed at intake for the very same harvest inputs, and it is
        the final figure — never the provisional one — that drives every settlement line."

        Design: Difficulty/dual_variant_calc/clean_unit_variant_divergence_provisional_vs_final
        """
        state = bagged_lot_state(api)
        lot = state["seed_lot"]
        assert_seed_lot(lot)

        assert lot["final_clean_units"] == pytest.approx(GOLDEN_FIGURES["FINAL_CLEAN_UNITS"], abs=0.01)
        assert lot["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert lot["provisional_clean_units"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )
        assert lot["final_clean_units"] != lot["provisional_clean_units"]
        assert lot["conditioning_status"] == "BAGGED"
        assert lot["certification_status"] == "UNSAMPLED"
        assert_lot_mass_conserved(lot)

    def test_bagging_leaves_the_contract_provisional_total_on_the_intake_variant(self, api):
        """The contract's running total stays on the provisional basis after bagging.

        PRD: "The harvest event's `provisional_clean_units` is added to the contract's
        `provisional_clean_units_total`."

        Design: Difficulty/dual_variant_calc/clean_unit_variant_divergence_provisional_vs_final
        """
        state = bagged_lot_state(api)
        contract = state["contract"]

        assert contract["provisional_clean_units_total"] == pytest.approx(
            GOLDEN_FIGURES["PROVISIONAL_CLEAN_UNITS"], abs=0.01
        )
        assert contract["certified_units_total"] == pytest.approx(0.0, abs=0.01)
        assert state["bagging_run"]["bag_count"] == GOLDEN_FIGURES["BAG_COUNT"]
        assert state["bagging_run"]["output_kg"] == pytest.approx(
            TEST_DEFAULTS["BAGGING_OUTPUT_KG"], abs=0.01
        )


def _restricted_history_field(api):
    """A field whose only prior crop is a restricted crop inside the look-back window."""
    variety = make_variety(api)
    grower = make_grower(api)
    field = make_production_field(
        api, grower["id"], field_code="F-South-3", acres=180.0, isolation_distance_m=250.0
    )
    make_field_history_record(api, field["id"], crop_kind="WHEAT", crop_year=2024)
    return variety, grower, field


class TestEligibilityVariantDivergence:
    def test_certified_class_binds_the_strict_variant_and_reports_ineligible(self, api):
        """One restricted record inside the window makes the strict variant refuse the field.

        PRD: "Under the **strict history** variant, the field is ineligible if it carries even
        one restricted record inside the look-back window, no matter how long ago that crop was
        grown; if there is no restricted record but the isolation shortfall is greater than
        zero, the field is also ineligible; otherwise it is eligible."

        Design: Difficulty/dual_variant_calc/eligibility_variant_divergence_strict_vs_decay
        """
        variety, _grower, field = _restricted_history_field(api)

        assessment = validate_success(
            api.create_eligibility_assessment(
                field["id"],
                create_eligibility_assessment_payload(variety["id"], season_year=2026, seed_class="CERTIFIED"),
                make_program_admin_headers(),
            ),
            200,
        )
        assert_eligibility_assessment(assessment)

        assert assessment["strict_history_result"] == "INELIGIBLE"
        assert assessment["decay_weighted_result"] == "ELIGIBLE"
        assert assessment["restricted_record_count"] == 1
        assert assessment["history_component"] == pytest.approx(25.00, abs=0.01)
        assert assessment["isolation_component"] == pytest.approx(0.00, abs=0.01)
        assert assessment["contamination_risk_score"] == pytest.approx(25.00, abs=0.01)
        assert assessment["isolation_shortfall_m"] == pytest.approx(0.00, abs=0.01)
        assert assessment["applied_variant"] == "STRICT_HISTORY"
        assert assessment["applied_result"] == "INELIGIBLE"
        assert assessment["blocking_error_id"] == "ERR_FIELD_HISTORY_RESTRICTED"

    def test_commercial_increase_class_binds_the_decay_variant_and_reports_eligible(self, api):
        """The same data is eligible once halving forgives the two-year-old transgression.

        PRD: "Because halving forgives distant history, the very same field, variety and season
        data can be eligible under the decay-weighted variant while being ineligible under the
        strict variant."

        Design: Difficulty/dual_variant_calc/eligibility_variant_divergence_strict_vs_decay
        """
        variety, _grower, field = _restricted_history_field(api)

        strict = validate_success(
            api.create_eligibility_assessment(
                field["id"],
                create_eligibility_assessment_payload(variety["id"], season_year=2026, seed_class="CERTIFIED"),
                make_program_admin_headers(),
            ),
            200,
        )
        decay = validate_success(
            api.create_eligibility_assessment(
                field["id"],
                create_eligibility_assessment_payload(
                    variety["id"], season_year=2026, seed_class="COMMERCIAL_INCREASE"
                ),
                make_program_admin_headers(),
            ),
            200,
        )
        assert_eligibility_assessment(decay)

        assert decay["strict_history_result"] == strict["strict_history_result"] == "INELIGIBLE"
        assert decay["decay_weighted_result"] == "ELIGIBLE"
        assert decay["applied_variant"] == "DECAY_WEIGHTED"
        assert decay["applied_result"] == "ELIGIBLE"
        assert decay["blocking_error_id"] is None
        assert decay["contamination_risk_score"] == pytest.approx(25.00, abs=0.01)
        assert decay["restricted_record_count"] == 1

    def test_assessment_writes_the_risk_score_onto_the_field(self, api):
        """The computed read-through is not side-effect free: it stamps the field.

        PRD: "The assessment does not mutate any contract, but it is not entirely side-effect
        free: it writes the computed contamination risk score onto the field's
        `last_assessed_risk_score` and increments the field's `version` by 1."

        Design: Difficulty/dual_variant_calc/eligibility_variant_divergence_strict_vs_decay
        """
        variety, _grower, field = _restricted_history_field(api)
        before = get_success_data(api.get_production_field(field["id"], make_program_admin_headers()))

        validate_success(
            api.create_eligibility_assessment(
                field["id"],
                create_eligibility_assessment_payload(
                    variety["id"], season_year=2026, seed_class="COMMERCIAL_INCREASE"
                ),
                make_program_admin_headers(),
            ),
            200,
        )

        after = get_success_data(api.get_production_field(field["id"], make_program_admin_headers()))
        assert after["last_assessed_risk_score"] == pytest.approx(25.00, abs=0.01)
        assert after["version"] == before["version"] + 1
