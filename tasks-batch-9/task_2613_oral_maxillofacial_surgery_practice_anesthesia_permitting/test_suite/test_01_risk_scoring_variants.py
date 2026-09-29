"""Pre-anesthesia risk scoring: the provisional variant at signature and the
final variant at day-of verification."""
import pytest

from test_helpers import (
    assert_evaluation,
    assert_risk_band_matches,
    create_evaluation_for,
    fetch_case,
    draft_case,
    set_env_clock,
    setup_practice_with_roster,
    sign_evaluation_as,
    verify_evaluation_as,
)

CLOCK = "2026-09-11T10:00:00Z"
CASE_START = "2026-09-14T13:00:00Z"
CASE_END = "2026-09-14T14:00:00Z"
# Patient born 1980-03-15 is 46 at the clock above: no age points either way.
PATIENT = {
    "full_name": "Pat Molar",
    "date_of_birth": "1980-03-15T00:00:00Z",
    "asa_class": 2,
    "airway_class": 2,
    "weight_kg": 80,
    "medical_plan_active": False,
    "dental_plan_active": True,
    "dental_annual_remaining_cents": 150000,
}


def _local_only_case_with_signed_evaluation():
    """One LOCAL_ONLY third-molar case whose evaluation records ASA 2 / airway 2 /
    one comorbidity and has been signed by its author."""
    env = setup_practice_with_roster(clock=CLOCK, patient_overrides=PATIENT)
    case = draft_case(
        env,
        planned_anesthesia_level="LOCAL_ONLY",
        planned_start=CASE_START,
        planned_end=CASE_END,
        procedure_category="THIRD_MOLAR",
        total_charge_cents=111110,
    )
    evaluation = create_evaluation_for(
        env, case["id"], env["monitor"]["id"],
        asa_class_recorded=2, airway_class_recorded=2, comorbidity_count=1,
    )
    signed = sign_evaluation_as(evaluation["id"], env["monitor"]["id"])
    return env, case, signed


def test_provisional_risk_score_is_the_multiplied_factor_block(api):
    """PRD 3.5: "Start from the recorded ASA class: base points are ten times
    `asa_class_recorded`."
    PRD 3.5: "Comorbidity points are three times `comorbidity_count`, capped at 12,
    so the fifth and later comorbidity add nothing."
    PRD 3.5: "That product, rounded half-up to two decimal places, is the core
    score, and it is the whole of `provisional_risk_score`."
    PRD 3.5: "`risk_band` is derived from whichever score the variant produced —
    from `final_risk_score` once the evaluation is `VERIFIED`, and from
    `provisional_risk_score` before that — using three floors: a score below 25 is
    `LOW`, a score from 25 up to but not including 40 is `ELEVATED`, a score from
    40 up to but not including 55 is `HIGH`, and a score of 55 or more is
    `PROHIBITIVE`."

    ASA 2 gives 20, airway 2 gives 0, age 46 gives 0, one comorbidity gives 3 and
    80 kg gives 0; the LOCAL_ONLY multiplier of one half turns that subtotal of 23
    into 11.50, which is band LOW.

    Design: Difficulty/dual_variant_calc/risk_score_provisional_versus_final_on_evaluation
    """
    env, case, signed = _local_only_case_with_signed_evaluation()

    assert_evaluation(signed)
    assert signed["status"] == "SIGNED"
    assert signed["provisional_risk_score"] == pytest.approx(11.5, abs=0.01), (
        f"provisional_risk_score must be 11.5, got {signed['provisional_risk_score']}"
    )
    assert signed["risk_band"] == "LOW", (
        f"a provisional score of 11.5 sits below the 25 floor and is LOW, got {signed['risk_band']}"
    )
    assert_risk_band_matches(signed["provisional_risk_score"], signed["risk_band"])
    assert signed["final_risk_score"] is None, (
        "final_risk_score stays null until day-of verification"
    )
    assert fetch_case(case["id"])["clearance_status"] == "EVALUATED"


def test_final_risk_score_adds_unscaled_fasting_penalty_and_jumps_a_band(api):
    """PRD 3.5: "The final variant runs at day-of verification and adds three flat
    penalties to the already-rounded core score, never to the subtotal — because
    they are applied after the multiplier, they are never scaled by it, which is
    why an otherwise identical evaluation can sit two bands apart between the two
    variants."
    PRD 3.5: "Fifteen points are added when `npo_solids_minutes` is under 480."
    PRD 3.5: "Ten points are added when `escort_confirmed` is false and the case's
    `planned_anesthesia_level` is anything other than `LOCAL_ONLY`."
    PRD 3.5: "Verification then computes the two fasting intervals:
    `npo_solids_minutes` is the whole minutes from `fasting_solids_last_at` to the
    logical clock at verification, and `npo_clears_minutes` is the whole minutes
    from `fasting_clears_last_at` to that same instant."

    Design: Difficulty/dual_variant_calc/risk_score_provisional_versus_final_on_evaluation
    """
    env, case, signed = _local_only_case_with_signed_evaluation()
    set_env_clock(env, CASE_START)

    verified = verify_evaluation_as(
        env, signed["id"], intent="CLEAR",
        solids_minutes_ago=360, clears_minutes_ago=120,
        escort_confirmed=False,
    )

    assert verified["status"] == "VERIFIED"
    assert verified["npo_solids_minutes"] == 360
    assert verified["npo_clears_minutes"] == 120
    assert verified["provisional_risk_score"] == pytest.approx(11.5, abs=0.01)
    assert verified["final_risk_score"] == pytest.approx(26.5, abs=0.01), (
        f"11.5 core plus the flat 15-point fasting penalty is 26.5, got {verified['final_risk_score']}"
    )
    assert verified["final_risk_score"] - verified["provisional_risk_score"] == pytest.approx(
        15.0, abs=0.01
    ), "the fasting penalty is flat and is never scaled by the LOCAL_ONLY multiplier"
    assert verified["risk_band"] == "ELEVATED", (
        f"a final score of 26.5 crosses the 25 floor into ELEVATED, got {verified['risk_band']}"
    )
    assert fetch_case(case["id"])["clearance_status"] == "CLEARED"
