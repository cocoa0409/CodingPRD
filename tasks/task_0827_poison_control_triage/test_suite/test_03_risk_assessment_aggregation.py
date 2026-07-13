"""Risk-assessment aggregation: the MAX vs ADDITIVE dual variant, the pinned
round-then-sum order, and the initial assessment state.

Translations of Difficulty rule `dual_variant_calc` / `combinatorial_formula`
and Corner `state_machines`.
"""
from test_helpers import (
    add_exposure,
    create_assessment,
    open_case,
    seed_specialist,
    seed_substance,
    triage,
)


def _build_two_exposure_case(api, spi, substances_and_doses, weight=20):
    """substances_and_doses: list of (substance_id, dose). Returns (case, case_version)."""
    case = open_case(api, spi["id"], patient_weight_kg=weight, chief_complaint="co-ingestion")
    for substance_id, dose in substances_and_doses:
        add_exposure(api, case["id"], spi["id"], substance_id,
                     dose_range_low_mg=dose, dose_range_high_mg=dose)
    triaged = triage(api, case["id"], spi["id"])
    return case, triaged["version"]


def test_aggregate_max_is_maximum_toxicity_score(api):
    """PRD §3.4: "The **MAX** variant, `aggregate_score_max`, is the maximum
    `toxicity_score` across all of the case's exposures, and its band — using the
    same thresholds as an exposure's severity band — becomes the assessment's
    `risk_tier`."

    Design: Difficulty/dual_variant_calc/aggregate_max_vs_additive
    """
    apap = seed_substance(api)  # tdk 150, onset 4
    ibu = seed_substance(api, name="ibuprofen", toxic_dose_mg_per_kg=100, onset_hours=2)
    spi = seed_specialist(api)
    case, ver = _build_two_exposure_case(api, spi, [(apap["id"], 3000), (ibu["id"], 600)])
    ra = create_assessment(api, case["id"], spi["id"], ver)
    assert ra["aggregate_score_max"] == 1.00
    assert ra["risk_tier"] == "SEVERE"


def test_aggregate_additive_coingestant_weighted_sum(api):
    """PRD §3.4: "the exposure's contribution is its `toxicity_score` multiplied by
    that weight, rounded half-up to 2 decimal places. These per-exposure
    contributions are rounded first and only then summed; the pinned order matters.
    A co-ingestant multiplier of 1.15 applies when at least two exposures have a
    `toxicity_score` of 0.25 or greater, and is 1.00 otherwise."

    Design: Difficulty/dual_variant_calc/aggregate_max_vs_additive
    """
    apap = seed_substance(api)
    ibu = seed_substance(api, name="ibuprofen", toxic_dose_mg_per_kg=100, onset_hours=2)
    spi = seed_specialist(api)
    case, ver = _build_two_exposure_case(api, spi, [(apap["id"], 3000), (ibu["id"], 600)])
    ra = create_assessment(api, case["id"], spi["id"], ver)
    assert ra["aggregate_score_additive"] == 1.78


def test_additive_rounds_each_contribution_before_summing(api):
    """PRD §3.4: "the exposure's contribution is its `toxicity_score` multiplied by
    that weight, rounded half-up to 2 decimal places. These per-exposure
    contributions are rounded first and only then summed; the pinned order matters."

    Design: Difficulty/combinatorial_formula/additive_round_per_exposure_then_sum
    """
    apap = seed_substance(api)
    spi = seed_specialist(api)
    case, ver = _build_two_exposure_case(api, spi, [(apap["id"], 2350), (apap["id"], 1650)])
    ra = create_assessment(api, case["id"], spi["id"], ver)
    assert ra["aggregate_score_additive"] == 1.76


def test_max_variant_independent_of_additive(api):
    """PRD §3.4: "The **MAX** variant, `aggregate_score_max`, is the maximum
    `toxicity_score` across all of the case's exposures, and its band — using the
    same thresholds as an exposure's severity band — becomes the assessment's
    `risk_tier`."

    Design: Difficulty/combinatorial_formula/additive_round_per_exposure_then_sum
    """
    apap = seed_substance(api)
    spi = seed_specialist(api)
    case, ver = _build_two_exposure_case(api, spi, [(apap["id"], 2350), (apap["id"], 1650)])
    ra = create_assessment(api, case["id"], spi["id"], ver)
    assert ra["aggregate_score_max"] == 0.78


def test_new_risk_assessment_starts_completed(api):
    """PRD §3.4: "A new assessment starts in `COMPLETED` status and immediately
    supersedes any prior active assessment on the case, moving that prior
    assessment to `SUPERSEDED`."

    Design: Corner/state_machines/risk_assessment_initial_state_completed
    """
    apap = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=20)
    add_exposure(api, case["id"], spi["id"], apap["id"])
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    assert ra["status"] == "COMPLETED"
