"""Difficulty queue - rule dual_variant_calc.

The two dual-basis calculations of the specification: the control score under
ONBOARDING_PROVISIONAL versus REFRESH_FINAL, and the wind-down cap under
FORWARD_PROJECTED versus CHRONOLOGICAL_ACTUAL.
"""
from test_helpers import (
    add_control_rows,
    add_verified_owner,
    approve_plan,
    calibrate,
    committee_decision,
    corridor,
    draft_plan,
    get_success_data,
    licensed_respondent,
    new_jurisdiction,
    new_respondent,
    open_profile,
    open_questionnaire,
    overlay_row,
    post_observation,
    read_plan,
    read_profile,
    read_respondent,
    score_respondent,
    submit_plan,
    submit_questionnaire,
    validate_success,
)
from test_helpers.fixtures import ANALYST, COMMITTEE, assess_questionnaire


SELF_FIVE = {
    "GOVERNANCE": 5, "KYC_ONBOARDING": 5, "TRANSACTION_MONITORING": 5,
    "SANCTIONS_SCREENING": 5, "PEP_HANDLING": 5, "TRAINING": 5,
    "AUDIT": 5, "NESTED_CONTROLS": 5,
}


def _provisional_respondent():
    """DE-style respondent whose first questionnaire is ASSESSED under
    ONBOARDING_PROVISIONAL with all eight rows at self_rating 5 and three
    analyst overlays."""
    code = new_jurisdiction(name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0)[
        "jurisdiction_code"
    ]
    respondent = licensed_respondent(code, legal_name="Rhein Handelsbank AG")
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Rhein Handels Holding")
    q1 = open_questionnaire(rid, version="V1")
    rows = add_control_rows(q1["id"], rid, SELF_FIVE)
    submit_questionnaire(q1["id"], rid)
    overlay_row(rows["GOVERNANCE"]["id"], assessed_rating=2)
    overlay_row(rows["SANCTIONS_SCREENING"]["id"], assessed_rating=3, gap_severity="MAJOR")
    overlay_row(rows["AUDIT"]["id"], assessed_rating=1)
    assess_questionnaire(q1["id"], "ONBOARDING_PROVISIONAL")
    score_respondent(rid, "ONBOARDING_PROVISIONAL")
    return code, rid, q1, rows


def test_onboarding_provisional_credits_self_rating_and_takes_the_one_major_cap(api):
    """ONBOARDING_PROVISIONAL credits self_rating for every un-overlaid domain, so
    the raw 78.80 is produced from three assessed ratings plus five self ratings and
    then clipped to 75.00 by the exactly-one-MAJOR clause.

    Design: Difficulty/dual_variant_calc/control_score_onboarding_self_credit_vs_refresh_assessed_only_same_respondent
    """
    code, rid, q1, rows = _provisional_respondent()

    stored = get_success_data(api.get_questionnaire(q1["id"], ANALYST))
    assert stored["state"] == "ASSESSED"
    assert stored["control_score_variant"] == "ONBOARDING_PROVISIONAL"
    # 0.10*2 + 0.18*5 + 0.20*5 + 0.22*3 + 0.10*5 + 0.05*5 + 0.08*1 + 0.07*5 = 3.94
    # 3.94 * 20.0 = 78.80 raw; exactly one MAJOR row caps the stored score at 75.00.
    assert stored["computed_control_score"] == 75.00

    respondent = read_respondent(rid)
    assert respondent["control_score"] == 75.00
    assert respondent["control_credit"] == 0.3094  # round(55.00/80.00*0.4500, 4)
    assert respondent["inherent_risk_score"] == 14.00  # 8.00 jurisdiction + 6 activity
    assert respondent["residual_risk_score"] == 9.67  # round(14.00*0.6906, 2)
    assert respondent["risk_rating"] == "LOW"


def test_refresh_final_ignores_self_rating_on_the_very_same_respondent(api):
    """The same respondent, a byte-identical second questionnaire and a full assessed
    set score 30.80 under REFRESH_FINAL because self_rating is ignored entirely, a
    44.20-point gap against the provisional 75.00 and the 75.00 cap left inert.

    Design: Difficulty/dual_variant_calc/control_score_onboarding_self_credit_vs_refresh_assessed_only_same_respondent
    """
    code, rid, q1, rows = _provisional_respondent()
    committee_decision(rid, "APPROVE")
    assert read_respondent(rid)["dd_state"] == "APPROVED"

    q2 = open_questionnaire(rid, version="V2")
    rows2 = add_control_rows(q2["id"], rid, SELF_FIVE)
    submit_questionnaire(q2["id"], rid)
    overlay_row(rows2["GOVERNANCE"]["id"], assessed_rating=2)
    overlay_row(rows2["SANCTIONS_SCREENING"]["id"], assessed_rating=3, gap_severity="MAJOR")
    for domain in (
        "KYC_ONBOARDING", "TRANSACTION_MONITORING", "PEP_HANDLING", "TRAINING",
        "AUDIT", "NESTED_CONTROLS",
    ):
        overlay_row(rows2[domain]["id"], assessed_rating=1)

    response = api.decide_assessment(
        q2["id"], {"action": "ASSESS", "variant": "REFRESH_FINAL"}, ANALYST
    )
    assessed = validate_success(response)

    assert assessed["control_score_variant"] == "REFRESH_FINAL"
    # 0.10*2 + 0.18*1 + 0.20*1 + 0.22*3 + 0.10*1 + 0.05*1 + 0.08*1 + 0.07*1 = 1.54
    assert assessed["computed_control_score"] == 30.80
    assert assessed["state"] == "ASSESSED"

    kyc = get_success_data(api.get_control_assessment(rows2["KYC_ONBOARDING"]["id"], ANALYST))
    assert kyc["self_rating"] == 5 and kyc["assessed_rating"] == 1

    sanctions = get_success_data(
        api.get_control_assessment(rows2["SANCTIONS_SCREENING"]["id"], ANALYST)
    )
    assert sanctions["remediation_required"] is True

    # The provisional questionnaire keeps its own frozen 75.00 while the respondent
    # now mirrors the refresh-final figure.
    frozen = get_success_data(api.get_questionnaire(q1["id"], ANALYST))
    assert frozen["computed_control_score"] == 75.00
    assert read_respondent(rid)["control_score"] == 30.80


def _cap_respondent(code):
    """Licensed, scored respondent with control_score 80.00 and risk_rating LOW."""
    respondent = licensed_respondent(code, legal_name="Rhein Handelsbank AG")
    rid = respondent["id"]
    questionnaire = open_questionnaire(rid, version="V1")
    add_control_rows(questionnaire["id"], rid, {d: 4 for d in SELF_FIVE})
    submit_questionnaire(questionnaire["id"], rid)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    score_respondent(rid, "ONBOARDING_PROVISIONAL")
    return rid


def test_forward_projected_cap_reads_the_declared_volume_and_ignores_activity(api):
    """FORWARD_PROJECTED takes the respondent's declared expected_monthly_volume_usd
    as the base, so a COMMERCIAL exit with no obligation and no observations at all
    carries 4500000.00 x 3.0 x 0.60 = 8100000.00.

    Design: Difficulty/dual_variant_calc/wind_down_cap_forward_projection_vs_capped_three_period_chronological_mean
    """
    code = new_jurisdiction(name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0)[
        "jurisdiction_code"
    ]
    respondent = new_respondent(
        code, legal_name="Bayern Aussenhandelsbank AG",
        expected_monthly_volume_usd=4500000.00, expected_monthly_count=300,
    )
    plan = draft_plan(
        respondent["id"], termination_reason="COMMERCIAL",
        cap_basis="FORWARD_PROJECTED", original_obligation_cents=0,
    )
    submit_plan(plan["id"])

    approved = validate_success(
        api.approve_closure_plan(plan["id"], {"action": "APPROVE"}, COMMITTEE)
    )

    assert approved["state"] == "APPROVED"
    assert approved["cap_basis"] == "FORWARD_PROJECTED"
    assert approved["notice_period_days"] == 90  # COMMERCIAL base, no obligation extension
    assert approved["wind_down_cap_usd"] == 8100000.00  # round(4500000.00*(90/30.0)*0.60, 2)


def test_chronological_actual_cap_means_the_last_three_capped_observation_months(api):
    """CHRONOLOGICAL_ACTUAL takes the last three distinct period months, clips each
    period total at 1.25 x aggregate_usd_threshold, and means them - 8833500.00
    against the identical declared volume that FORWARD_PROJECTED turns into
    8100000.00.

    Design: Difficulty/dual_variant_calc/wind_down_cap_forward_projection_vs_capped_three_period_chronological_mean
    """
    code = new_jurisdiction(name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0)[
        "jurisdiction_code"
    ]
    rid = _cap_respondent(code)
    assert read_respondent(rid)["risk_rating"] == "LOW"

    profile = open_profile(
        rid, [corridor(code, 4000000.00, 200)], tolerance_pct=0.15,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z",
    )
    calibrate(profile["id"])
    calibrated = read_profile(profile["id"])
    assert calibrated["calibration_state"] == "CALIBRATED"
    # 4000000.00 * 1.15 * 1.30 / 1.00 = 5980000.00 per corridor, buffered by 1.10.
    assert calibrated["aggregate_usd_threshold"] == 6578000.00
    assert calibrated["hold_threshold_usd"] == 657800.00

    post_observation(profile["id"], "2026-04", code, aggregate_usd=1000000.00, txn_count=10)
    post_observation(profile["id"], "2026-05", code, aggregate_usd=3000000.00, txn_count=10)
    june = post_observation(
        profile["id"], "2026-06", code, aggregate_usd=9500000.00, txn_count=10
    )
    post_observation(profile["id"], "2026-07", code, aggregate_usd=3500000.00, txn_count=10)

    stored_june = get_success_data(api.get_activity_observation(june["id"], ANALYST))
    assert stored_june["usd_threshold_applied"] == 5980000.00
    assert stored_june["breach_ratio"] == 1.5886  # round(9500000.00/5980000.00, 4)

    plan = draft_plan(
        rid, termination_reason="COMMERCIAL", cap_basis="CHRONOLOGICAL_ACTUAL",
        original_obligation_cents=0,
    )
    submit_plan(plan["id"])
    approve_plan(plan["id"])

    stored = read_plan(plan["id"])
    assert stored["state"] == "APPROVED"
    assert stored["cap_basis"] == "CHRONOLOGICAL_ACTUAL"
    assert stored["notice_period_days"] == 90
    # 2026-06 clipped to round(1.25*6578000.00, 2) = 8222500.00; mean of
    # 3000000.00, 8222500.00 and 3500000.00 is 4907500.00.
    assert stored["wind_down_cap_usd"] == 8833500.00  # round(4907500.00*3.0*0.60, 2)
