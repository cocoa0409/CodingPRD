"""Risk-screening score computation: dual variants, non-linear caps, band boundary."""
from test_helpers import (
    api_client as api,
    validate_success, validate_error,
    create_risk_screening_payload, TEST_USERS,
    create_contact,
)

SUP = TEST_USERS["supervisor_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]


# ─── dual_variant_calc / risk_score_provisional_vs_comprehensive_diverge ───────

def test_provisional_screening_ignores_protective_and_scores_imminent():
    """PRD §3.2: "For a `PROVISIONAL` screening the protective term is zero — protective factors are ignored during rapid triage, which yields the higher score."
    PRD §3.2: "the `risk_band` is `IMMINENT` when the score is at least 20; otherwise `HIGH` when the score is at least 12; otherwise `MODERATE` when the score is at least 6; otherwise `LOW`."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_comprehensive_diverge
    """
    c = create_contact("dvc-prov-01", channel="PHONE")
    res = api.create_risk_screening(create_risk_screening_payload(
        c["id"], screening_type="PROVISIONAL", suicidal_ideation=2, plan_specificity=2,
        means_access=True, prior_attempts=1, protective_factors=2), COUNSELOR)
    sc = validate_success(res, 201)
    assert sc["risk_score"] == 21, f"expected PROVISIONAL score 21, got {sc['risk_score']}"
    assert sc["risk_band"] == "IMMINENT", f"expected IMMINENT, got {sc['risk_band']}"


def test_comprehensive_screening_subtracts_protective_and_scores_high():
    """PRD §3.2: "For a `COMPREHENSIVE` screening the protective term is the `protective_factors` count, capped at 3, multiplied by 2, which lowers the score and can pull the contact into a lower band."
    PRD §3.2: "the `risk_band` is `IMMINENT` when the score is at least 20; otherwise `HIGH` when the score is at least 12; otherwise `MODERATE` when the score is at least 6; otherwise `LOW`."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_vs_comprehensive_diverge
    """
    c = create_contact("dvc-comp-01", channel="PHONE")
    res = api.create_risk_screening(create_risk_screening_payload(
        c["id"], screening_type="COMPREHENSIVE", suicidal_ideation=2, plan_specificity=2,
        means_access=True, prior_attempts=1, protective_factors=2), COUNSELOR)
    sc = validate_success(res, 201)
    assert sc["risk_score"] == 17, f"expected COMPREHENSIVE score 17, got {sc['risk_score']}"
    assert sc["risk_band"] == "HIGH", f"expected HIGH, got {sc['risk_band']}"


# ─── combinatorial_formula / risk_score_nonlinear_caps_and_conditional_means ───

def test_screening_caps_ideation_prior_protective_scores_26():
    """PRD §3.2: "The ideation component is the `suicidal_ideation` value, capped at 3, multiplied by 3."
    PRD §3.2: "The prior-attempts component is `prior_attempts` capped at 3, multiplied by 2."
    PRD §3.2: "For a `COMPREHENSIVE` screening the protective term is the `protective_factors` count, capped at 3, multiplied by 2, which lowers the score and can pull the contact into a lower band."

    Design: Difficulty/combinatorial_formula/risk_score_nonlinear_caps_and_conditional_means
    """
    c = create_contact("cf-a-01", channel="CHAT")
    res = api.create_risk_screening(create_risk_screening_payload(
        c["id"], screening_type="COMPREHENSIVE", suicidal_ideation=5, plan_specificity=3,
        means_access=True, prior_attempts=9, protective_factors=9), COUNSELOR)
    sc = validate_success(res, 201)
    assert sc["risk_score"] == 26, f"expected capped score 26, got {sc['risk_score']}"
    assert sc["risk_band"] == "IMMINENT", f"expected IMMINENT, got {sc['risk_band']}"


def test_screening_means_bonus_is_conditional_flat_five():
    """PRD §3.2: "If `means_access` is true, a flat 5 points are added; if false, this component contributes nothing."

    Design: Difficulty/combinatorial_formula/risk_score_nonlinear_caps_and_conditional_means
    """
    c = create_contact("cf-a-02", channel="CHAT")
    res = api.create_risk_screening(create_risk_screening_payload(
        c["id"], screening_type="COMPREHENSIVE", suicidal_ideation=5, plan_specificity=3,
        means_access=False, prior_attempts=9, protective_factors=9), COUNSELOR)
    sc = validate_success(res, 201)
    # Identical to the score-26 case except means_access=false, which drops exactly 5 -> 21.
    assert sc["risk_score"] == 21, f"expected 21 without means bonus, got {sc['risk_score']}"


# ─── boundary_precision_check / risk_band_high_threshold_ge_boundary ───────────

def test_risk_band_high_at_threshold_12():
    """PRD §3.2: "the `risk_band` is `IMMINENT` when the score is at least 20; otherwise `HIGH` when the score is at least 12; otherwise `MODERATE` when the score is at least 6; otherwise `LOW`."

    Design: Difficulty/boundary_precision_check/risk_band_high_threshold_ge_boundary
    """
    c = create_contact("bp-12", channel="CHAT")
    res = api.create_risk_screening(create_risk_screening_payload(
        c["id"], screening_type="COMPREHENSIVE", suicidal_ideation=0, plan_specificity=3,
        means_access=False, prior_attempts=0, protective_factors=0), COUNSELOR)
    sc = validate_success(res, 201)
    assert sc["risk_score"] == 12, f"expected score 12, got {sc['risk_score']}"
    assert sc["risk_band"] == "HIGH", f"score 12 must band HIGH, got {sc['risk_band']}"


def test_risk_band_moderate_just_below_high_threshold_11():
    """PRD §3.2: "the `risk_band` is `IMMINENT` when the score is at least 20; otherwise `HIGH` when the score is at least 12; otherwise `MODERATE` when the score is at least 6; otherwise `LOW`."

    Design: Difficulty/boundary_precision_check/risk_band_high_threshold_ge_boundary
    """
    c = create_contact("bp-11", channel="CHAT")
    res = api.create_risk_screening(create_risk_screening_payload(
        c["id"], screening_type="COMPREHENSIVE", suicidal_ideation=1, plan_specificity=2,
        means_access=False, prior_attempts=0, protective_factors=0), COUNSELOR)
    sc = validate_success(res, 201)
    assert sc["risk_score"] == 11, f"expected score 11, got {sc['risk_score']}"
    assert sc["risk_band"] == "MODERATE", f"score 11 must band MODERATE, got {sc['risk_band']}"


# ─── Corner / risk_screening_invalid_type_enum_returns_error ───────────────────

def test_screening_invalid_type_enum_rejected():
    """PRD §2.8: "body-field validity — required fields present and well-formed (`ERR_VALIDATION`), enum fields carrying an allowed value (`ERR_INVALID_ENUM`), and dated windows satisfying end-after-start (`ERR_WINDOW_INVALID`)"

    Design: Corner/entities/risk_screening_invalid_type_enum_returns_error
    """
    c = create_contact("ie-01", channel="CHAT")
    res = api.create_risk_screening({
        "contact_id": c["id"], "screening_type": "BOGUS", "suicidal_ideation": 1,
        "plan_specificity": 1, "means_access": False, "prior_attempts": 0,
    }, COUNSELOR)
    validate_error(res, "ERR_INVALID_ENUM", expected_status=422)
