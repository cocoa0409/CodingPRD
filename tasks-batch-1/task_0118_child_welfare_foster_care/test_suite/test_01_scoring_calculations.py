"""Intake screening and safety-assessment score calculations.

Queue A — difficulty rules: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    get_success_data, validate_success,
    setup_workers, create_screened_in_referral, create_investigation_in_progress,
    decide_investigation,
)


# =========================================================================
# Rule 1 — dual_variant_calc / intake_screening_variant_in_vs_out
# =========================================================================
def test_intake_screen_in_variant_score_and_priority(api):
    """PRD §3.1: "for each distinct danger factor present in `priority_factors`, add its weight — `PRIOR_REPORT` adds 10, `CAREGIVER_SUBSTANCE` adds 12, `INJURY_VISIBLE` adds 15, `AGE_UNDER_3` adds 18, and `NO_CAREGIVER` adds 30 — counting each factor only once even if it appears more than once."
    PRD §3.1: "A referral is screened in when its `screening_score` is at least 45; otherwise it is screened out. The response-timeframe band is then: a score of at least 75 yields `P1_24H`; a score of at least 45 but below 75 yields `P2_72H`; and a score below 45 yields `P3_10D`."
    PHYSICAL_ABUSE(40)+INJURY_VISIBLE(15)+PRIOR_REPORT(10)+MANDATED(8)=73 -> SCREENED_IN, P2_72H.

    Design: Difficulty/dual_variant_calc/intake_screening_variant_in_vs_out
    """
    w = setup_workers(need_licensing=False)
    ref = get_success_data(api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child A",
         "alleged_maltreatment": "PHYSICAL_ABUSE",
         "priority_factors": ["INJURY_VISIBLE", "PRIOR_REPORT"]}, w.screener))
    screened = validate_success(api.screen_referral(ref["id"], w.screener))
    assert screened["screening_score"] == 73, f"expected 73, got {screened['screening_score']}"
    assert screened["status"] == "SCREENED_IN"
    assert screened["response_priority"] == "P2_72H"
    assert screened["screened_in_by"] == w.screener_id


def test_intake_screen_out_variant_score_and_priority(api):
    """PRD §3.1: "Start from a base weight determined by the alleged maltreatment type: `SEXUAL_ABUSE` contributes 50, `PHYSICAL_ABUSE` contributes 40, `NEGLECT` contributes 25, and `EMOTIONAL_ABUSE` contributes 20."
    PRD §3.1: "Then add a reporter bonus keyed on `reporter_type`: `MANDATED` adds 8, `RELATIVE` adds 4, `SELF` adds 2, and `ANONYMOUS` adds nothing."
    PRD §3.1: "By construction, every screened-out referral carries `P3_10D".
    EMOTIONAL_ABUSE(20)+[]+ANONYMOUS(0)=20 < 45 -> SCREENED_OUT, P3_10D.

    Design: Difficulty/dual_variant_calc/intake_screening_variant_in_vs_out
    """
    w = setup_workers(need_licensing=False)
    ref = get_success_data(api.create_referral(
        {"reporter_type": "ANONYMOUS", "child_name": "Child B",
         "alleged_maltreatment": "EMOTIONAL_ABUSE", "priority_factors": []}, w.screener))
    screened = validate_success(api.screen_referral(ref["id"], w.screener))
    assert screened["screening_score"] == 20, f"expected 20, got {screened['screening_score']}"
    assert screened["status"] == "SCREENED_OUT"
    assert screened["response_priority"] == "P3_10D"


# =========================================================================
# Rule 1 — dual_variant_calc / safety_assessment_variant_removal_vs_safe
# =========================================================================
def test_safety_decision_removal_variant(api):
    """PRD §3.2: "Sum the weight of each distinct confirmed safety factor: `NO_FOOD` weighs 25, `VIOLENCE_PRESENT` weighs 35, `SUPERVISION_ABSENT` weighs 30, `MEDICAL_NEGLECT` weighs 28, `DRUG_ENV` weighs 22, and `UNSAFE_SLEEP` weighs 18".
    PRD §3.2: "A score of at least 70 yields `UNSAFE` and sets `removal_recommended` to true (the present-danger override therefore always lands here)."
    NO_FOOD(25)+MEDICAL_NEGLECT(28)+DRUG_ENV(22)+UNSAFE_SLEEP(18)=93, pc 0 credit 0 -> 93 -> UNSAFE.

    Design: Difficulty/dual_variant_calc/safety_assessment_variant_removal_vs_safe
    """
    w = setup_workers(need_licensing=False)
    inv = create_investigation_in_progress(w)
    decided = validate_success(api.decide_investigation(
        inv["id"], {"safety_factors": ["NO_FOOD", "MEDICAL_NEGLECT", "DRUG_ENV", "UNSAFE_SLEEP"],
                    "protective_capacity": 0}, w.investigator))
    assert decided["safety_decision_score"] == 93, f"got {decided['safety_decision_score']}"
    assert decided["status"] == "UNSAFE"
    assert decided["removal_recommended"] is True


def test_safety_decision_safe_variant(api):
    """PRD §3.2: "the credit equals the smaller of the danger value and the product of `protective_capacity` and six, so the credit can never exceed danger. The net is the danger value minus the credit, floored at zero (never negative)."
    PRD §3.2: "A score below 40 yields `SAFE`, sets `removal_recommended` to false, and opens no case."
    NO_FOOD(25); pc 5 -> credit min(25,30)=25; net 0; no override -> 0 -> SAFE.

    Design: Difficulty/dual_variant_calc/safety_assessment_variant_removal_vs_safe
    """
    w = setup_workers(need_licensing=False)
    inv = create_investigation_in_progress(w)
    decided = validate_success(api.decide_investigation(
        inv["id"], {"safety_factors": ["NO_FOOD"], "protective_capacity": 5}, w.investigator))
    assert decided["safety_decision_score"] == 0, f"got {decided['safety_decision_score']}"
    assert decided["status"] == "SAFE"
    assert decided["removal_recommended"] is False


# =========================================================================
# Rule 2 — combinatorial_formula / safety_score_nested_minmax_with_conditional_override
# =========================================================================
def test_safety_score_present_danger_override_forces_removal_band(api):
    """PRD §3.2: "If the confirmed `safety_factors` include `VIOLENCE_PRESENT` or `SUPERVISION_ABSENT`, the safety decision score is the larger of the net and 70, forcing the result into the removal band; otherwise the safety decision score is simply the net. This three-step order — credit, then floored net, then override — is load-bearing and must be evaluated exactly as stated."
    SUPERVISION_ABSENT(30)+NO_FOOD(25)=55; pc 10 -> credit min(55,60)=55; net 0;
    override fires -> max(0,70)=70 -> UNSAFE.

    Design: Difficulty/combinatorial_formula/safety_score_nested_minmax_with_conditional_override
    """
    w = setup_workers(need_licensing=False)
    inv = create_investigation_in_progress(w)
    decided = validate_success(api.decide_investigation(
        inv["id"], {"safety_factors": ["SUPERVISION_ABSENT", "NO_FOOD"],
                    "protective_capacity": 10}, w.investigator))
    assert decided["safety_decision_score"] == 70, f"got {decided['safety_decision_score']}"
    assert decided["status"] == "UNSAFE"
    assert decided["removal_recommended"] is True


def test_safety_score_protective_credit_capped_at_danger(api):
    """PRD §3.2: "The caregiver's protective capacity offsets danger, but the credit is capped: the credit equals the smaller of the danger value and the product of `protective_capacity` and six, so the credit can never exceed danger. The net is the danger value minus the credit, floored at zero (never negative)."
    NO_FOOD(25) danger; pc 10 -> raw credit 60 but capped at danger 25; net 0; no
    override -> score 0 -> SAFE (credit never overshoots danger into a negative net).

    Design: Difficulty/combinatorial_formula/safety_score_nested_minmax_with_conditional_override
    """
    w = setup_workers(need_licensing=False)
    inv = create_investigation_in_progress(w)
    decided = validate_success(api.decide_investigation(
        inv["id"], {"safety_factors": ["NO_FOOD"], "protective_capacity": 10}, w.investigator))
    assert decided["safety_decision_score"] == 0, f"got {decided['safety_decision_score']}"
    assert decided["status"] == "SAFE"
    assert decided["removal_recommended"] is False


# =========================================================================
# Rule 2 — combinatorial_formula / screening_score_ceiling_clamp_order
# =========================================================================
def test_screening_score_ceiling_clamp_applied_after_summation(api):
    """PRD §3.1: "The stored `screening_score` is that raw total **capped at a ceiling of 100** — if the raw total exceeds 100, the score is 100; the cap is applied only after the full summation, never to the individual terms."
    SEXUAL_ABUSE(50)+NO_CAREGIVER(30)+INJURY_VISIBLE(15)+AGE_UNDER_3(18)+MANDATED(8)=121
    -> clamp to 100.

    Design: Difficulty/combinatorial_formula/screening_score_ceiling_clamp_order
    """
    w = setup_workers(need_licensing=False)
    ref = get_success_data(api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child C",
         "alleged_maltreatment": "SEXUAL_ABUSE",
         "priority_factors": ["NO_CAREGIVER", "INJURY_VISIBLE", "AGE_UNDER_3"]}, w.screener))
    screened = validate_success(api.screen_referral(ref["id"], w.screener))
    assert screened["screening_score"] == 100, f"expected clamp to 100, got {screened['screening_score']}"
    assert screened["status"] == "SCREENED_IN"


def test_screening_score_ceiling_clamp_priority_band_p1(api):
    """PRD §3.1: "The screen-in decision and the `response_priority` band both read the **capped** score."
    PRD §3.1: "a score of at least 75 yields `P1_24H`".
    Clamped score 100 (>= 75) -> P1_24H, proving the band reads the clamped value.

    Design: Difficulty/combinatorial_formula/screening_score_ceiling_clamp_order
    """
    w = setup_workers(need_licensing=False)
    ref = get_success_data(api.create_referral(
        {"reporter_type": "MANDATED", "child_name": "Child C2",
         "alleged_maltreatment": "SEXUAL_ABUSE",
         "priority_factors": ["NO_CAREGIVER", "INJURY_VISIBLE", "AGE_UNDER_3"]}, w.screener))
    screened = validate_success(api.screen_referral(ref["id"], w.screener))
    assert screened["screening_score"] == 100
    assert screened["response_priority"] == "P1_24H"
