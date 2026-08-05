"""Biometric scoring: band selection, the self-attested variant and its boundaries."""

from test_helpers import (
    assert_health_assessment,
    new_clinic_assessment,
    new_self_attested_assessment,
    setup_checked_in_visit,
    setup_clinic,
)


def _scoring_world(code, name, member, participant_name="Score Tester"):
    return setup_checked_in_visit(
        visit_type="WELLNESS",
        scheduled_start="2026-06-08T09:00:00Z",
        visit_clock="2026-06-08T10:00:00Z",
        employer={"legal_name": name, "employer_code": code},
        site={"site_name": f"{code} Clinic", "daily_slot_capacity": 8},
        eligibility={
            "subscriber_external_id": f"S-{member}",
            "member_external_id": f"M-{member}",
        },
        participant={"display_name": participant_name},
    )


def test_clinic_measured_metrics_score_five_points_and_meet_the_standard():
    """PRD §3.6: "Blood pressure scores 3 points when the systolic value is at least
    140 or the diastolic value is at least 90; failing that, 2 points when the
    systolic value falls between 130 and 139 with both ends included, or the diastolic
    value falls between 80 and 89 with both ends included; failing that, 1 point when
    the systolic value falls between 120 and 129 with both ends included *and* the
    diastolic value is strictly below 80; and 0 points otherwise, that is when the
    systolic value is strictly below 120 and the diastolic value is strictly below 80."
    PRD §3.6: "On a `CLINIC_MEASURED` assessment `risk_points_total` is simply
    `risk_points_raw`, unadjusted."
    PRD §3.6: "`outcome_standard_met` is true when `risk_points_total` is 5 or less,
    the bound being inclusive, and false otherwise. `outcome_credit_status` starts as
    `MET_DIRECT` when the standard was met and `PENDING_ALTERNATIVE` when it was not;
    the third value, `CREDITED_VIA_RAS`, is reachable only through the
    alternative-standard cascade below and never at creation."

    Design: Difficulty/dual_variant_calc/hra_score_clinic_measured_vs_self_attested_flips_outcome_standard
    """
    world = _scoring_world("NWM", "Northwind Manufacturing", "1001", "Ana Silva")

    assessment = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=132,
        diastolic_mmhg=78,
        bmi=27.4,
        a1c_pct=5.7,
        ldl_mg_dl=118,
        cotinine_ng_ml=2.0,
    )

    assert_health_assessment(assessment)
    assert assessment["risk_points_raw"] == 5
    assert assessment["risk_points_total"] == 5
    assert assessment["risk_band"] == "MODERATE"
    assert assessment["outcome_standard_met"] is True
    assert assessment["outcome_credit_status"] == "MET_DIRECT"


def test_self_attested_multiplier_lifts_the_same_metrics_past_the_standard():
    """PRD §3.6: "On a `SELF_ATTESTED` assessment `risk_points_total` is
    `risk_points_raw` multiplied by 1.25 and then rounded half-up to a whole number —
    unverified numbers are discounted by loading the score. Identical measurements
    therefore score higher when self-attested than when clinic-measured, and that
    difference can by itself flip a participant from meeting the outcome standard to
    not meeting it."
    PRD §3.6: "On a `SELF_ATTESTED` assessment tobacco scores 3 points when
    `self_reported_tobacco` is true and 0 points otherwise, the answer coming from the
    participant's own declaration."

    Design: Difficulty/dual_variant_calc/hra_score_clinic_measured_vs_self_attested_flips_outcome_standard
    """
    world = _scoring_world("NWM", "Northwind Manufacturing", "1001", "Ana Silva")

    measured = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=132,
        diastolic_mmhg=78,
        bmi=27.4,
        a1c_pct=5.7,
        ldl_mg_dl=118,
        cotinine_ng_ml=2.0,
    )
    attested = new_self_attested_assessment(
        world.participant_id,
        measurement_date="2026-06-08",
        systolic_mmhg=132,
        diastolic_mmhg=78,
        bmi=27.4,
        a1c_pct=5.7,
        ldl_mg_dl=118,
        self_reported_tobacco=False,
    )

    assert attested["risk_points_raw"] == 5
    assert attested["risk_points_raw"] == measured["risk_points_raw"], (
        "the raw score is the same on identical measurements"
    )
    assert attested["risk_points_total"] == 6
    assert attested["risk_band"] == "MODERATE"
    assert attested["outcome_standard_met"] is False
    assert attested["outcome_credit_status"] == "PENDING_ALTERNATIVE"
    assert measured["outcome_standard_met"] is True


def test_blood_pressure_band_ors_over_two_axes_and_composes_to_six_points():
    """PRD §3.6: "Blood pressure scores 3 points when the systolic value is at least
    140 or the diastolic value is at least 90; failing that, 2 points when the
    systolic value falls between 130 and 139 with both ends included, or the diastolic
    value falls between 80 and 89 with both ends included; failing that, 1 point when
    the systolic value falls between 120 and 129 with both ends included *and* the
    diastolic value is strictly below 80; and 0 points otherwise, that is when the
    systolic value is strictly below 120 and the diastolic value is strictly below 80."
    PRD §3.6: "Body-mass index scores 3 points at 35.0 or above, 2 points from 30.0
    inclusive up to but not including 35.0, 1 point from 25.0 inclusive up to but not
    including 30.0, and 0 points strictly below 25.0. A1c scores 3 points at 6.5 or
    above, 1 point from 5.7 inclusive up to but not including 6.5, and 0 points
    strictly below 5.7 — there is no 2-point A1c band. LDL scores 2 points at 160 or
    above, 1 point from 100 inclusive up to but not including 160, and 0 points
    strictly below 100."
    PRD §3.6: "On a `CLINIC_MEASURED` assessment tobacco scores 3 points when
    `cotinine_ng_ml` is 10.0 or above and 0 points otherwise, the answer coming from
    the assay."

    Design: Difficulty/combinatorial_formula/hra_band_selection_uses_highest_matching_band_across_five_metrics
    """
    world = _scoring_world("BND", "Band Test Co", "6001", "Bo Chen")

    assessment = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=118,
        diastolic_mmhg=88,
        bmi=34.9,
        a1c_pct=6.4,
        ldl_mg_dl=159,
        cotinine_ng_ml=9.9,
    )

    assert assessment["risk_points_raw"] == 6, (
        "an optimal systolic paired with a stage-1 diastolic still scores 2 BP points"
    )
    assert assessment["risk_points_total"] == 6
    assert assessment["risk_band"] == "MODERATE"
    assert assessment["outcome_standard_met"] is False


def test_every_metric_at_its_severe_band_scores_fourteen_points():
    """PRD §3.6: "Body-mass index scores 3 points at 35.0 or above, 2 points from 30.0
    inclusive up to but not including 35.0, 1 point from 25.0 inclusive up to but not
    including 30.0, and 0 points strictly below 25.0. A1c scores 3 points at 6.5 or
    above, 1 point from 5.7 inclusive up to but not including 6.5, and 0 points
    strictly below 5.7 — there is no 2-point A1c band. LDL scores 2 points at 160 or
    above, 1 point from 100 inclusive up to but not including 160, and 0 points
    strictly below 100."
    PRD §3.6: "`risk_band` is `LOW` when `risk_points_total` is 3 or less, `MODERATE`
    when it falls between 4 and 7 with both ends included, and `HIGH` when it is 8 or
    more."

    Design: Difficulty/combinatorial_formula/hra_band_selection_uses_highest_matching_band_across_five_metrics
    """
    world = _scoring_world("BND", "Band Test Co", "6001", "Bo Chen")

    assessment = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=140,
        diastolic_mmhg=78,
        bmi=35.0,
        a1c_pct=6.5,
        ldl_mg_dl=160,
        cotinine_ng_ml=10.0,
    )

    assert assessment["risk_points_raw"] == 14
    assert assessment["risk_points_total"] == 14
    assert assessment["risk_band"] == "HIGH"
    assert assessment["outcome_standard_met"] is False
    assert assessment["outcome_credit_status"] == "PENDING_ALTERNATIVE"


def test_a1c_at_the_prediabetes_floor_scores_one_point():
    """PRD §3.6: "A1c scores 3 points at 6.5 or above, 1 point from 5.7 inclusive up
    to but not including 6.5, and 0 points strictly below 5.7 — there is no 2-point
    A1c band."
    PRD §3.6: "`risk_band` is `LOW` when `risk_points_total` is 3 or less, `MODERATE`
    when it falls between 4 and 7 with both ends included, and `HIGH` when it is 8 or
    more."

    Design: Difficulty/boundary_precision_check/a1c_exactly_at_prediabetes_floor_scores_one_point
    """
    world = _scoring_world("EDG", "Edge Co", "1401", "Edge Case")

    assessment = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=118,
        diastolic_mmhg=76,
        bmi=24.9,
        a1c_pct=5.7,
        ldl_mg_dl=99,
        cotinine_ng_ml=1.0,
    )

    assert assessment["risk_points_raw"] == 1
    assert assessment["risk_points_total"] == 1
    assert assessment["risk_band"] == "LOW"
    assert assessment["outcome_standard_met"] is True
    assert assessment["outcome_credit_status"] == "MET_DIRECT"


def test_a1c_just_below_the_prediabetes_floor_scores_zero():
    """PRD §3.6: "A1c scores 3 points at 6.5 or above, 1 point from 5.7 inclusive up
    to but not including 6.5, and 0 points strictly below 5.7 — there is no 2-point
    A1c band."
    PRD §3.6: "`outcome_standard_met` is true when `risk_points_total` is 5 or less,
    the bound being inclusive, and false otherwise."

    Design: Difficulty/boundary_precision_check/a1c_exactly_at_prediabetes_floor_scores_one_point
    """
    world = _scoring_world("EDG", "Edge Co", "1401", "Edge Case")

    at_floor = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=118,
        diastolic_mmhg=76,
        bmi=24.9,
        a1c_pct=5.7,
        ldl_mg_dl=99,
        cotinine_ng_ml=1.0,
    )
    below_floor = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=118,
        diastolic_mmhg=76,
        bmi=24.9,
        a1c_pct=5.6,
        ldl_mg_dl=99,
        cotinine_ng_ml=1.0,
    )

    assert below_floor["risk_points_raw"] == 0
    assert below_floor["risk_points_total"] == 0
    assert below_floor["risk_band"] == "LOW"
    assert at_floor["risk_points_total"] - below_floor["risk_points_total"] == 1
    assert below_floor["outcome_standard_met"] is True
    assert below_floor["outcome_credit_status"] == "MET_DIRECT"


def test_self_attested_absent_metrics_each_add_one_point():
    """PRD §3.6: "On a `SELF_ATTESTED` assessment, the blood-pressure pair counts as
    one metric and is absent only when both `systolic_mmhg` and `diastolic_mmhg` are
    omitted; each of the blood-pressure pair, `a1c_pct` and `ldl_mg_dl` that is absent
    contributes exactly 1 point instead of the 0 it would otherwise have scored, so an
    assessment with none of the three supplied carries 3 points of missing-metric
    penalty."
    PRD §3.6: "A `SELF_ATTESTED` assessment requires only `bmi` and
    `self_reported_tobacco`; the rest may be omitted, and their absence is scored
    rather than rejected."
    PRD §3.6: "A `CLINIC_MEASURED` row must name the in-clinic `visit_id` that
    produced the measurements; a `SELF_ATTESTED` row must leave `visit_id` null."

    Design: Corner/calculations/self_attested_missing_metrics_each_score_one_point
    """
    world = setup_clinic(
        employer={"legal_name": "Attest Co", "employer_code": "ATS"},
        contract=False,
        shift=False,
        eligibility={
            "subscriber_external_id": "S-4301",
            "member_external_id": "M-4301",
            "tier": "DEPENDENT",
        },
        participant={"display_name": "Attest Tester"},
    )

    assessment = new_self_attested_assessment(
        world.participant_id,
        measurement_date="2026-06-01",
        bmi=26.0,
        self_reported_tobacco=False,
    )

    assert_health_assessment(assessment)
    assert assessment["risk_points_raw"] == 4, (
        "1 point for bmi plus one each for the absent BP pair, a1c and ldl"
    )
    assert assessment["risk_points_total"] == 5
    assert assessment["risk_band"] == "MODERATE"
    assert assessment["outcome_standard_met"] is True
    assert assessment["outcome_credit_status"] == "MET_DIRECT"
    assert assessment["visit_id"] is None
