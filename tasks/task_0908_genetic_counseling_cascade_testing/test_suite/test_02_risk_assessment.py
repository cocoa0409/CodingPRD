"""Pedigree-based prior-risk calculation, risk tiering, and assess-risk preconditions.

Translates queue-A difficulty instances (combinatorial prior risk, HIGH-boundary
tiering) and queue-B corner instances (empty-pedigree precondition).
"""
import pytest
from test_helpers import (
    validate_error, make_counselor_headers,
    setup_risk_assessed_case, create_family, create_counselor,
)


# --------------------------------------------------------------------------- #
# Difficulty: prior_risk_multifactor_nonlinear
# --------------------------------------------------------------------------- #
def test_prior_risk_multifactor_nonlinear_value(api):
    """PRD 3.4: "Each contributing member earns a degree weight — 1.0 for a
    first-degree member, 0.5 for a second-degree member, and 0.25 for a third-degree
    member, while a self or degree-zero member and any unrecognized degree contribute
    a weight of zero — multiplied by an onset multiplier keyed on age_of_onset: 3 when
    onset is before age 40, 2 when onset is at least 40 but before 50, and 1 when onset
    is 50 or older; an unknown or null onset also uses a multiplier of 1." PRD 3.4:
    "The raw risk is a population baseline of 0.05 plus 0.05 for each affected unit. If
    the case's ancestry is ASHKENAZI_JEWISH, a bonus of 0.10 is added; otherwise no
    bonus applies."

    Design: Difficulty/combinatorial_formula/prior_risk_multifactor_nonlinear
    """
    ctx = setup_risk_assessed_case(
        members=[
            {"relationship": "PARENT", "degree": 1, "affected": True, "age_of_onset": 45},
            {"relationship": "AUNT_UNCLE", "degree": 2, "affected": True, "age_of_onset": 38},
        ],
        ancestry="ASHKENAZI_JEWISH", covered_sessions=2)
    # (1.0*2) + (0.5*3) = 3.5 units; 0.05 + 3.5*0.05 + 0.10 = 0.325
    assert ctx["case"]["prior_risk_pct"] == pytest.approx(0.325, abs=1e-6)


def test_prior_risk_multifactor_nonlinear_tier_high(api):
    """PRD 3.6: "The tier is HIGH when that probability is at least 0.20, MODERATE when
    it is at least 0.10 but below 0.20, and LOW when it is below 0.10. The 0.20 high
    boundary is inclusive."

    Design: Difficulty/combinatorial_formula/prior_risk_multifactor_nonlinear
    """
    ctx = setup_risk_assessed_case(
        members=[
            {"relationship": "PARENT", "degree": 1, "affected": True, "age_of_onset": 45},
            {"relationship": "AUNT_UNCLE", "degree": 2, "affected": True, "age_of_onset": 38},
        ],
        ancestry="ASHKENAZI_JEWISH", covered_sessions=2)
    assert ctx["case"]["risk_tier"] == "HIGH"


# --------------------------------------------------------------------------- #
# Difficulty: risk_tier_high_inclusive_at_exactly_020
# --------------------------------------------------------------------------- #
def test_prior_risk_exactly_020(api):
    """PRD 3.4: "The raw risk is a population baseline of 0.05 plus 0.05 for each
    affected unit." PRD 3.4: degree weight "1.0 for a first-degree member" and onset
    multiplier "3 when onset is before age 40".

    Design: Difficulty/boundary_precision_check/risk_tier_high_inclusive_at_exactly_020
    """
    ctx = setup_risk_assessed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 35}],
        ancestry="EUROPEAN", covered_sessions=1)
    # 1.0*3 = 3 units; 0.05 + 3*0.05 = 0.20
    assert ctx["case"]["prior_risk_pct"] == pytest.approx(0.2, abs=1e-6)


def test_risk_tier_high_inclusive_at_020(api):
    """PRD 3.6: "The tier is HIGH when that probability is at least 0.20, MODERATE when
    it is at least 0.10 but below 0.20, and LOW when it is below 0.10. The 0.20 high
    boundary is inclusive."

    Design: Difficulty/boundary_precision_check/risk_tier_high_inclusive_at_exactly_020
    """
    ctx = setup_risk_assessed_case(
        members=[{"relationship": "SIBLING", "degree": 1, "affected": True,
                  "age_of_onset": 35}],
        ancestry="EUROPEAN", covered_sessions=1)
    assert ctx["case"]["prior_risk_pct"] == pytest.approx(0.2, abs=1e-6)
    assert ctx["case"]["risk_tier"] == "HIGH"


# --------------------------------------------------------------------------- #
# Corner: assess_risk_empty_pedigree_rejected
# --------------------------------------------------------------------------- #
def test_assess_risk_empty_pedigree_rejected(api):
    """PRD 3.4: "Once at least one pedigree member exists, a counselor runs risk
    assessment on a case that is still at INTAKE; a case in any other clinical state is
    rejected with ERR_CASE_INVALID_CLINICAL_STATE, and a case with no pedigree members
    is rejected with ERR_PEDIGREE_EMPTY."

    Design: Corner/state_machines/assess_risk_empty_pedigree_rejected
    """
    fam = create_family(name="Kindred I")
    gc = create_counselor()
    hdr = make_counselor_headers(gc["id"])
    from test_helpers import create_case_payload, validate_success
    case = validate_success(
        api.create_case(create_case_payload(fam["id"], gc["id"], covered_sessions=1), hdr), 201)
    res = api.assess_risk(case["id"], hdr)
    validate_error(res, "ERR_PEDIGREE_EMPTY", expected_status=409)
    after = validate_success(api.get_case(case["id"], hdr), 200)
    assert after["clinical_status"] == "INTAKE"
