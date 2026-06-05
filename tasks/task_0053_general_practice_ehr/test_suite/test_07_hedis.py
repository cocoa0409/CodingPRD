"""HEDIS eligibility, compliance-rate variants, and the empty-denominator
boundary.
"""
import pytest
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock,
    create_provider,
    create_patient,
    create_hedis_measure,
)

FD = TEST_USERS["frontdesk_headers"]
QA = TEST_USERS["quality_headers"]
BILLER = TEST_USERS["biller_headers"]


# ─── Queue A: dual_variant_calc / hedis_administrative_vs_hybrid_rate_diverge ───
#
# The asserted divergence is that HYBRID additionally counts chart_confirmed GAP
# rows. To keep the outcome uniquely derivable from PRD prose alone, the
# population uses only the chart_confirmed mechanism (PRD §3.10) — it does not
# depend on a finalize-cascade flip, whose "matching HEDIS measure" wording leaves
# open whether a PHYSICAL visit satisfies a BCS_MAMMOGRAM measure specifically.

def _build_mammogram_population():
    """Four eligible (female, age 60) GAP BCS_MAMMOGRAM measures for 2026:
    one with chart_confirmed=true, three with chart_confirmed=false. All four are
    GAP, so ADMINISTRATIVE numerator is 0 while HYBRID adds the one chart-confirmed
    row."""
    set_clock("2026-06-01T00:00:00Z")
    patients = [create_patient(first_name=f"W{i}", date_of_birth="1966-03-10", sex="F")
                for i in range(4)]
    create_hedis_measure(patients[0]["id"], measure_type="BCS_MAMMOGRAM",
                         measurement_year=2026, method="HYBRID", chart_confirmed=True)
    for p in patients[1:]:
        create_hedis_measure(p["id"], measure_type="BCS_MAMMOGRAM",
                             measurement_year=2026, method="HYBRID")


def test_administrative_rate_counts_only_numerator_compliant(api):
    """PRD §3.10: "Under `ADMINISTRATIVE`, the numerator counts only those measures
    whose status is `NUMERATOR_COMPLIANT`."

    Design: Difficulty/dual_variant_calc/hedis_administrative_vs_hybrid_rate_diverge
    """
    _build_mammogram_population()
    res = api.get_hedis_rate(QA, params={
        "measure_type": "BCS_MAMMOGRAM", "measurement_year": 2026, "method": "ADMINISTRATIVE",
    })
    data = validate_success(res, 200)
    # All four rows are GAP, so the administrative numerator (NUMERATOR_COMPLIANT
    # only) is 0; the chart_confirmed GAP row is not counted under ADMINISTRATIVE.
    assert data["denominator"] == 4
    assert data["numerator"] == 0
    assert data["rate_pct"] == 0, (
        f"administrative numerator counts NUMERATOR_COMPLIANT only (0/4 -> 0), got {data['rate_pct']}"
    )


def test_hybrid_rate_also_counts_chart_confirmed_gap(api):
    """PRD §3.10: "Under `HYBRID`, the numerator additionally counts measures that are
    still in `GAP` status but whose `chart_confirmed` is true, so hybrid yields a rate at
    least as high as administrative on identical data."

    Design: Difficulty/dual_variant_calc/hedis_administrative_vs_hybrid_rate_diverge
    """
    _build_mammogram_population()
    res = api.get_hedis_rate(QA, params={
        "measure_type": "BCS_MAMMOGRAM", "measurement_year": 2026, "method": "HYBRID",
    })
    data = validate_success(res, 200)
    # HYBRID additionally counts the one chart_confirmed GAP row: 1/4 -> 25.0,
    # strictly higher than the administrative rate on identical data.
    assert data["denominator"] == 4
    assert data["numerator"] == 1
    assert data["rate_pct"] == 25.0, (
        f"hybrid adds the chart_confirmed GAP row (1/4 -> 25.0), got {data['rate_pct']}"
    )


# ─── Queue A: boundary_precision_check / hedis_rate_empty_denominator_zero ───

def test_empty_denominator_rate_is_zero(api):
    """PRD §3.10: "when the denominator is zero the rate is the integer 0."

    Design: Difficulty/boundary_precision_check/hedis_rate_empty_denominator_zero
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_hedis_rate(QA, params={
        "measure_type": "CBP_BP_CONTROL", "measurement_year": 2026, "method": "ADMINISTRATIVE",
    })
    data = validate_success(res, 200)
    assert data["denominator"] == 0
    assert data["rate_pct"] == 0, (
        f"empty-population rate must be 0, got {data['rate_pct']}"
    )


def test_empty_denominator_numerator_is_zero(api):
    """PRD §3.10: "The denominator is the count of measures of that type and year that
    are eligible and not excluded."

    Design: Difficulty/boundary_precision_check/hedis_rate_empty_denominator_zero
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_hedis_rate(QA, params={
        "measure_type": "CBP_BP_CONTROL", "measurement_year": 2026, "method": "ADMINISTRATIVE",
    })
    data = validate_success(res, 200)
    assert data["numerator"] == 0, (
        f"empty population must yield numerator 0, got {data['numerator']}"
    )


# ─── Queue B: calculations / hedis_eligibility_age_below_window_excluded ───

def test_mammogram_age_below_window_ineligible(api):
    """PRD §3.10: "`BCS_MAMMOGRAM` covers ages 50 through 74... A patient is in the
    eligible population when their age falls at or above the window's minimum and at or
    below its maximum."

    Design: Corner/calculations/hedis_eligibility_age_below_window_excluded
    """
    # DOB 1977-01-01 -> age 49 at Dec 31 2026 (below min 50).
    patient = create_patient(first_name="Young", date_of_birth="1977-01-01", sex="F")
    measure = create_hedis_measure(patient["id"], measure_type="BCS_MAMMOGRAM",
                                   measurement_year=2026, method="ADMINISTRATIVE")
    assert measure["eligible"] is False, (
        f"age 49 is below the BCS_MAMMOGRAM min_age 50 -> eligible must be false, "
        f"got {measure['eligible']}"
    )


# ─── Queue B: calculations / hedis_eligibility_age_at_max_boundary_eligible ───

def test_mammogram_age_at_max_boundary_eligible(api):
    """PRD §3.10: "Each measure type has an inclusive age window — both bounds count...
    `BCS_MAMMOGRAM` covers ages 50 through 74."

    Design: Corner/calculations/hedis_eligibility_age_at_max_boundary_eligible
    """
    # DOB 1952-01-01 -> age 74 at Dec 31 2026 (== max 74, inclusive).
    patient = create_patient(first_name="Edge", date_of_birth="1952-01-01", sex="F")
    measure = create_hedis_measure(patient["id"], measure_type="BCS_MAMMOGRAM",
                                   measurement_year=2026, method="ADMINISTRATIVE")
    assert measure["eligible"] is True, (
        f"age 74 equals BCS_MAMMOGRAM max_age 74 (inclusive) -> eligible must be true, "
        f"got {measure['eligible']}"
    )


# ─── Queue B: calculations / bcs_mammogram_male_sex_ineligible ───

def test_mammogram_male_ineligible(api):
    """PRD §3.10: "because the mammogram measure is sex-specific — when, for
    `BCS_MAMMOGRAM` only, the patient's `sex` is `F`."

    Design: Corner/calculations/bcs_mammogram_male_sex_ineligible
    """
    # Male aged 60 (in age window) but sex-ineligible for mammogram.
    patient = create_patient(first_name="Male", date_of_birth="1966-03-10", sex="M")
    measure = create_hedis_measure(patient["id"], measure_type="BCS_MAMMOGRAM",
                                   measurement_year=2026, method="ADMINISTRATIVE")
    assert measure["eligible"] is False, (
        f"a male patient is ineligible for BCS_MAMMOGRAM regardless of age, "
        f"got eligible={measure['eligible']}"
    )
