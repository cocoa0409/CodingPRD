"""Result disclosure: carrier-result mapping, residual-risk projection, and the
depth-3 disclosure cascade (case -> surveillance plan -> referral).

Translates queue-A difficulty instances (dual-variant carrier risk, transitive cascade)
and queue-B corner instances (uninformative-negative residual).
"""
import pytest
from test_helpers import (
    validate_paginated, make_counselor_headers, setup_disclosed_case,
)


# --------------------------------------------------------------------------- #
# Difficulty: carrier_risk_prior_vs_residual_on_case
# --------------------------------------------------------------------------- #
def test_prior_risk_is_pretest_pedigree_only(api):
    """PRD 3.4: "The raw risk is a population baseline of 0.05 plus 0.05 for each
    affected unit." PRD 3.4: degree weight "1.0 for a first-degree member" and onset
    multiplier "3 when onset is before age 40".

    Design: Difficulty/dual_variant_calc/carrier_risk_prior_vs_residual_on_case
    """
    ctx = setup_disclosed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 35}],
        classification="BENIGN", familial_variant_known=True, ancestry="EUROPEAN",
        covered_sessions=3)
    assert ctx["case"]["prior_risk_pct"] == pytest.approx(0.2, abs=1e-6)


def test_residual_risk_true_negative_collapses_to_baseline(api):
    """PRD 3.6: "PATHOGENIC or LIKELY_PATHOGENIC map to POSITIVE_PATHOGENIC, BENIGN or
    LIKELY_BENIGN map to NEGATIVE, and VUS maps to VUS." PRD 3.6: "A NEGATIVE result
    branches on whether the family's variant was known: when familial_variant_known is
    true this is a true negative and the residual risk collapses to the population
    baseline of 0.05". PRD 3.6: "The tier is ... LOW when it is below 0.10."

    Design: Difficulty/dual_variant_calc/carrier_risk_prior_vs_residual_on_case
    """
    ctx = setup_disclosed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 35}],
        classification="BENIGN", familial_variant_known=True, ancestry="EUROPEAN",
        covered_sessions=3)
    case = ctx["case"]
    assert case["residual_risk_pct"] == pytest.approx(0.05, abs=1e-6)
    assert case["carrier_result"] == "NEGATIVE"
    assert case["risk_tier"] == "LOW"


# --------------------------------------------------------------------------- #
# Difficulty: disclose_positive_cascades_to_plan_and_referral_depth3
# --------------------------------------------------------------------------- #
def test_disclose_positive_updates_case(api):
    """PRD 3.6: "A POSITIVE_PATHOGENIC result sets the residual risk to the
    confirmed-carrier value of 0.99." PRD 3.6: "If the disclosed result is actionable,
    the system auto-creates an ACTIVE surveillance plan for the case, copying the case's
    risk_tier onto the plan and deriving screening_interval_months from that tier — 6
    months for HIGH, 12 for MODERATE, 24 for LOW — and the case advances from DISCLOSED
    to SURVEILLANCE."

    Design: Difficulty/transitive_cascade/disclose_positive_cascades_to_plan_and_referral_depth3
    """
    ctx = setup_disclosed_case(
        members=[{"relationship": "PARENT", "degree": 1, "affected": True,
                  "age_of_onset": 35}],
        classification="PATHOGENIC", familial_variant_known=False, covered_sessions=3)
    case = ctx["case"]
    assert case["carrier_result"] == "POSITIVE_PATHOGENIC"
    assert case["residual_risk_pct"] == pytest.approx(0.99, abs=1e-6)
    assert case["clinical_status"] == "SURVEILLANCE"


def test_disclose_positive_auto_creates_plan_and_referral(api):
    """PRD 3.6: "If the disclosed result is actionable, the system auto-creates an
    ACTIVE surveillance plan for the case, copying the case's risk_tier onto the plan
    and deriving screening_interval_months from that tier — 6 months for HIGH, 12 for
    MODERATE, 24 for LOW". PRD 3.6: "If that auto-created plan's risk_tier is HIGH, the
    system further auto-creates a PENDING referral linked to the plan, with specialty
    HIGH_RISK_CLINIC and urgency ROUTINE."

    Design: Difficulty/transitive_cascade/disclose_positive_cascades_to_plan_and_referral_depth3
    """
    ctx = setup_disclosed_case(
        members=[{"relationship": "PARENT", "degree": 1, "affected": True,
                  "age_of_onset": 35}],
        classification="PATHOGENIC", familial_variant_known=False, covered_sessions=3)
    hdr = make_counselor_headers(ctx["counselor_id"])

    plans, pmeta = validate_paginated(
        api.list_surveillance_plans(hdr, params={"counseling_case_id": ctx["case_id"]}))
    assert pmeta["total_count"] == 1
    assert plans[0]["status"] == "ACTIVE"
    assert plans[0]["risk_tier"] == "HIGH"
    assert plans[0]["screening_interval_months"] == 6

    refs, rmeta = validate_paginated(
        api.list_referrals(hdr, params={"counseling_case_id": ctx["case_id"]}))
    assert rmeta["total_count"] == 1
    assert refs[0]["status"] == "PENDING"
    assert refs[0]["specialty"] == "HIGH_RISK_CLINIC"


# --------------------------------------------------------------------------- #
# Corner: residual_uninformative_negative_halves_prior
# --------------------------------------------------------------------------- #
def test_residual_uninformative_negative_halves_prior(api):
    """PRD 3.6: "when it is false the negative is uninformative and the residual risk is
    the case's prior_risk_pct multiplied by an uninformative factor of 0.5, rounded half
    up to four decimal places." PRD 3.6: "The tier is ... MODERATE when it is at least
    0.10 but below 0.20".

    Design: Corner/calculations/residual_uninformative_negative_halves_prior
    """
    ctx = setup_disclosed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 35}],
        classification="BENIGN", familial_variant_known=False, ancestry="EUROPEAN",
        covered_sessions=2)
    case = ctx["case"]
    assert case["residual_risk_pct"] == pytest.approx(0.1, abs=1e-6)
    assert case["risk_tier"] == "MODERATE"
