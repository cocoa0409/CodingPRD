"""Suitability scoring: the two assessment bases and the height boundary."""

from test_helpers import (
    assert_assessment,
    assert_money,
    assert_ratio,
    assert_score,
    create_building,
    get_assessment,
    get_building,
    open_assessment,
    submit_assessment,
    decide_assessment,
    utility_headroom_ratio,
    weighted_suitability_score,
)

# The base building whose nameplate figures every case in this module measures
# against: 14.0 ft floor to floor, 95 psf live load, VC_C, a 60000 CFM riser and
# 800 kW of emergency power.
NAMEPLATE = {
    "name": "Kendall Labs 400",
    "published_floor_to_floor_ft": 14.0,
    "published_live_load_psf": 95,
    "published_vibration_class": "VC_C",
    "exhaust_riser_capacity_cfm": 60000,
    "emergency_power_capacity_kw": 800,
    "chilled_water_capacity_tons": 1200,
}

# Demanded of the plate by both bases: VC_C, 50000 CFM and 700 kW.
DEMAND = {
    "required_vibration_class": "VC_C",
    "required_exhaust_cfm": 50000,
    "required_power_kw": 700,
    "measured_live_load_psf": 88,
}


def test_screening_basis_substitutes_nameplate_figures_and_scores_78_0(api):
    """A screening assessment falls back to the published figures for anything unmeasured.

    Neither floor-to-floor height nor vibration class was measured, so a
    screening assessment reads the building's published 14.0 ft and published
    VC_C, earning full credit on both, and lands on a suitable verdict.

    Design: Difficulty/dual_variant_calc/assessment_screening_vs_investigation_divergence
    """
    building = create_building(api, **NAMEPLATE)
    assessment = open_assessment(
        api, building["id"], assessment_basis="SCREENING", **DEMAND
    )
    submitted = submit_assessment(api, assessment["id"])

    assert_assessment(submitted)
    assert submitted["assessment_basis"] == "SCREENING"
    assert submitted["height_credit"] == 100
    assert submitted["vibration_credit"] == 100
    assert submitted["structural_credit"] == 60
    assert submitted["utility_credit"] == 60
    assert_score(submitted["suitability_score"], 78.0)
    assert submitted["verdict"] == "SUITABLE"
    assert submitted["hard_fail_capped"] is False
    assert_score(
        submitted["suitability_score"], weighted_suitability_score(100, 60, 100, 60)
    )


def test_investigation_basis_scores_33_0_on_the_very_same_inputs(api):
    """An investigation assessment awards nothing for a dimension it did not measure.

    The payload is identical to the screening case apart from the basis, yet
    unmeasured height and unmeasured vibration each earn zero rather than
    falling back to the published figures, dropping the score to an unsuitable
    verdict.

    Design: Difficulty/dual_variant_calc/assessment_screening_vs_investigation_divergence
    """
    building = create_building(api, **NAMEPLATE)
    assessment = open_assessment(
        api, building["id"], assessment_basis="INVESTIGATION", **DEMAND
    )
    submitted = submit_assessment(api, assessment["id"])

    assert_assessment(submitted)
    assert submitted["assessment_basis"] == "INVESTIGATION"
    assert submitted["height_credit"] == 0
    assert submitted["vibration_credit"] == 0
    assert submitted["structural_credit"] == 60
    assert submitted["utility_credit"] == 60
    assert_score(submitted["suitability_score"], 33.0)
    assert submitted["verdict"] == "UNSUITABLE"
    assert submitted["hard_fail_capped"] is False, (
        "the cap only bites when the weighted sum would otherwise exceed 49.0"
    )


def test_shared_dimensions_agree_and_the_accepted_verdict_survives_reopening(api):
    """The basis changes only the dimensions that depend on a measurement.

    A measured live load and the nameplate utility quotient produce the same
    credits under both bases, and opening a second assessment returns the
    building to assessing while leaving the verdict recorded by the accepted
    assessment in place.

    Design: Difficulty/dual_variant_calc/assessment_screening_vs_investigation_divergence
    """
    building = create_building(api, **NAMEPLATE)
    screening = submit_assessment(
        api,
        open_assessment(
            api, building["id"], assessment_basis="SCREENING", **DEMAND
        )["id"],
    )
    decide_assessment(api, screening["id"], "ACCEPT")
    after_accept = get_building(api, building["id"])
    assert after_accept["suitability_state"] == "ASSESSED_SUITABLE"
    assert after_accept["latest_assessment_verdict"] == "SUITABLE"

    investigation = submit_assessment(
        api,
        open_assessment(
            api, building["id"], assessment_basis="INVESTIGATION", **DEMAND
        )["id"],
    )

    assert screening["structural_credit"] == investigation["structural_credit"] == 60
    expected_ratio = utility_headroom_ratio(60000, 50000, 800, 700)
    assert_ratio(screening["utility_headroom_ratio"], expected_ratio)
    assert_ratio(investigation["utility_headroom_ratio"], expected_ratio)
    assert_ratio(screening["utility_headroom_ratio"], 1.1429)

    reopened = get_building(api, building["id"])
    assert reopened["suitability_state"] == "ASSESSING"
    assert reopened["latest_assessment_verdict"] == "SUITABLE", (
        "only an accepted decision writes the building's recorded verdict"
    )


def test_height_of_exactly_12_50_earns_partial_credit_and_scores_68_0(api):
    """The marginal height threshold is inclusive at exactly 12.5 feet.

    A measured 12.50 ft plate earns partial rather than zero height credit, so
    no dimension fails outright, the cap stays off and the deal is suitable with
    conversion.

    Design: Difficulty/boundary_precision_check/suitability_height_boundary_12_50_scores_68_0_and_12_49_caps_to_49_0
    """
    building = create_building(api, **NAMEPLATE)
    assessment = open_assessment(
        api,
        building["id"],
        assessment_basis="INVESTIGATION",
        required_vibration_class="VC_C",
        required_exhaust_cfm=50000,
        required_power_kw=700,
        measured_floor_to_floor_ft=12.50,
        measured_live_load_psf=95,
        measured_vibration_class="VC_C",
    )
    submitted = submit_assessment(api, assessment["id"])

    assert submitted["height_credit"] == 60
    assert submitted["structural_credit"] == 60
    assert submitted["vibration_credit"] == 100
    assert submitted["utility_credit"] == 60
    assert_score(submitted["suitability_score"], 68.0)
    assert submitted["verdict"] == "SUITABLE_WITH_CONVERSION"
    assert submitted["hard_fail_capped"] is False


def test_height_of_12_49_zeroes_the_dimension_and_is_pulled_down_to_49_0(api):
    """One hundredth of a foot below the threshold trips the hard-fail cap.

    A measured 12.49 ft plate earns zero height credit; the weighted sum of
    53.0 would still read as conditional, so the cap forces the score to exactly
    49.0 and the verdict to unsuitable.

    Design: Difficulty/boundary_precision_check/suitability_height_boundary_12_50_scores_68_0_and_12_49_caps_to_49_0
    """
    building = create_building(api, **NAMEPLATE)
    assessment = open_assessment(
        api,
        building["id"],
        assessment_basis="INVESTIGATION",
        required_vibration_class="VC_C",
        required_exhaust_cfm=50000,
        required_power_kw=700,
        measured_floor_to_floor_ft=12.49,
        measured_live_load_psf=95,
        measured_vibration_class="VC_C",
    )
    submitted = submit_assessment(api, assessment["id"])

    assert submitted["height_credit"] == 0
    assert submitted["structural_credit"] == 60
    assert submitted["vibration_credit"] == 100
    assert submitted["utility_credit"] == 60
    # The weighted sum of these credits is 53.0, which the cap overrides.
    assert submitted["suitability_score"] < weighted_suitability_score(0, 60, 100, 60)
    assert_score(submitted["suitability_score"], 49.0)
    assert submitted["hard_fail_capped"] is True
    assert submitted["verdict"] == "UNSUITABLE"


def test_the_capped_assessment_does_not_disturb_the_earlier_accepted_verdict(api):
    """The building keeps the verdict its accepted assessment wrote.

    The 12.50 ft assessment is accepted and carries the building to a
    conditional posture; opening the 12.49 ft assessment returns the building to
    assessing, and submitting it leaves the recorded verdict untouched because
    no decision has been taken on it.

    Design: Difficulty/boundary_precision_check/suitability_height_boundary_12_50_scores_68_0_and_12_49_caps_to_49_0
    """
    building = create_building(api, **NAMEPLATE)
    measured = {
        "assessment_basis": "INVESTIGATION",
        "required_vibration_class": "VC_C",
        "required_exhaust_cfm": 50000,
        "required_power_kw": 700,
        "measured_live_load_psf": 95,
        "measured_vibration_class": "VC_C",
    }
    high = submit_assessment(
        api,
        open_assessment(
            api, building["id"], measured_floor_to_floor_ft=12.50, **measured
        )["id"],
    )
    decided = decide_assessment(api, high["id"], "ACCEPT")
    assert decided["status"] == "ACCEPTED"
    assert get_building(api, building["id"])["suitability_state"] == (
        "ASSESSED_CONDITIONAL"
    )

    low = open_assessment(
        api, building["id"], measured_floor_to_floor_ft=12.49, **measured
    )
    submit_assessment(api, low["id"])

    building_now = get_building(api, building["id"])
    assert building_now["suitability_state"] == "ASSESSING"
    assert building_now["latest_assessment_verdict"] == "SUITABLE_WITH_CONVERSION"
    assert_money(get_assessment(api, high["id"])["suitability_score"], 68.0, "score")
    assert get_assessment(api, low["id"])["hard_fail_capped"] is True
