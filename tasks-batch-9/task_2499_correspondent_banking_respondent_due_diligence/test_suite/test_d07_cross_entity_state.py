"""Difficulty queue - rule cross_entity_state_dependency.

Two transitions whose admissibility or output is decided by state living on another
entity: refresh completion gated on the respondent's own `last_risk_assessed_at`, and
observation alerting gated on the parent profile's `calibration_state`.
"""
from test_helpers import (
    ApiErrorId,
    add_control_rows,
    add_verified_owner,
    alerts_for,
    assert_instant_equals,
    calibrate,
    committee_decision,
    corridor,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    overlay_row,
    post_observation,
    progress_refresh,
    read_profile,
    read_refresh,
    read_respondent,
    schedule_refresh,
    score_respondent,
    set_clock,
    submit_questionnaire,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANALYST, assess_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]

REFRESH_OVERLAY = {
    "GOVERNANCE": 4, "KYC_ONBOARDING": 4, "TRANSACTION_MONITORING": 4,
    "SANCTIONS_SCREENING": 4, "PEP_HANDLING": 4, "TRAINING": 1, "AUDIT": 1,
    "NESTED_CONTROLS": 1,
}


def _approved_low(code, **overrides):
    respondent = licensed_respondent(code, **overrides)
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Sole Holding", ownership_pct=100.00)
    questionnaire = open_questionnaire(rid, version="V1")
    add_control_rows(questionnaire["id"], rid, {d: 3 for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], rid)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    assert scored["control_score"] == 60.00
    assert scored["control_credit"] == 0.2250
    assert scored["inherent_risk_score"] == 14.00
    assert scored["residual_risk_score"] == 10.85  # round(14.00*0.7750, 2)
    assert scored["risk_rating"] == "LOW"
    committee_decision(rid, "APPROVE")
    return rid


def _stale_assessment_cycle():
    """Cycle IN_PROGRESS from 2026-08-12 with a REFRESH_FINAL assessment taken two days
    too early and a fresh ASSESSED refresh questionnaire scoring 68.00."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    rid = _approved_low(
        code, legal_name="Leipzig Korrespondenzbank AG",
        expected_monthly_volume_usd=2000000.00, expected_monthly_count=100,
    )

    cycle = schedule_refresh(
        rid, "2026-08-10T00:00:00Z", "2026-11-08T00:00:00Z", trigger_reason="CADENCE"
    )
    assert read_respondent(rid)["dd_state"] == "REFRESH_DUE"

    # The refresh-final assessment is run BEFORE the cycle starts.
    set_clock("2026-08-10T00:00:00Z")
    early = score_respondent(rid, "REFRESH_FINAL")
    assert early["control_score"] == 20.00  # no assessed_rating anywhere, so 1 everywhere
    assert early["control_credit"] == 0.0000
    assert early["residual_risk_score"] == 14.00

    set_clock("2026-08-12T00:00:00Z")
    progress_refresh(cycle["id"], "START")

    set_clock("2026-08-13T00:00:00Z")
    second = open_questionnaire(rid, version="V2")
    rows = add_control_rows(second["id"], rid, {d: 2 for d in DOMAINS})
    submit_questionnaire(second["id"], rid)
    for domain, rating in REFRESH_OVERLAY.items():
        overlay_row(rows[domain]["id"], assessed_rating=rating)
    assessed = assess_questionnaire(second["id"], "REFRESH_FINAL")
    assert assessed["computed_control_score"] == 68.00  # 20.0 * (0.80*4 + 0.20*1)
    assert assessed["control_score_variant"] == "REFRESH_FINAL"

    return rid, cycle, second


def test_refresh_completion_rejects_an_assessment_taken_before_started_at(api):
    """The respondent already carries `risk_assessment_variant` REFRESH_FINAL and already
    has a questionnaire assessed inside the cycle, yet the completion is still refused
    because `last_risk_assessed_at` predates `started_at`.

    Design: Difficulty/cross_entity_state_dependency/refresh_completion_needs_a_refresh_final_assessment_timestamped_at_or_after_started_at
    """
    rid, cycle, second = _stale_assessment_cycle()
    before = read_refresh(cycle["id"])
    assert before["state"] == "IN_PROGRESS"
    assert_instant_equals(before["started_at"], "2026-08-12T00:00:00Z")

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "UNDER_REFRESH"
    assert respondent["risk_assessment_variant"] == "REFRESH_FINAL"  # right variant
    assert_instant_equals(respondent["last_risk_assessed_at"], "2026-08-10T00:00:00Z")

    response = api.progress_refresh(cycle["id"], {"action": "COMPLETE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_REFRESH_NOT_REASSESSED)

    after = read_refresh(cycle["id"])
    assert after["state"] == "IN_PROGRESS"
    assert after["completed_at"] is None
    assert read_respondent(rid)["dd_state"] == "UNDER_REFRESH"


def test_refresh_completion_snapshots_the_reassessment_taken_inside_the_cycle(api):
    """Re-running the assessment inside the cycle both admits the completion and changes
    the numbers, so the snapshot on the closed cycle proves which assessment was in force.

    Design: Difficulty/cross_entity_state_dependency/refresh_completion_needs_a_refresh_final_assessment_timestamped_at_or_after_started_at
    """
    rid, cycle, second = _stale_assessment_cycle()
    validate_error(
        api.progress_refresh(cycle["id"], {"action": "COMPLETE"}, ANALYST),
        ApiErrorId.ERR_REFRESH_NOT_REASSESSED,
    )

    rescored = validate_success(api.assess_risk(rid, {"variant": "REFRESH_FINAL"}, ANALYST))
    assert rescored["control_score"] == 68.00
    assert rescored["control_credit"] == 0.2700  # round((68.00-20)/80*0.45, 4)
    assert rescored["residual_risk_score"] == 10.22  # round(14.00*0.7300, 2)
    assert rescored["risk_rating"] == "LOW"
    assert_instant_equals(rescored["last_risk_assessed_at"], "2026-08-13T00:00:00Z")
    assert rescored["dd_state"] == "UNDER_REFRESH"  # the assessment alone completes nothing

    completed = validate_success(
        api.progress_refresh(cycle["id"], {"action": "COMPLETE"}, ANALYST)
    )

    assert completed["state"] == "COMPLETED"
    assert_instant_equals(completed["completed_at"], "2026-08-13T00:00:00Z")
    assert completed["completed_control_score"] == 68.00  # not the stale 20.00
    assert completed["completion_risk_rating"] == "LOW"
    assert completed["cadence_months_applied"] == 36  # frozen at schedule time
    assert completed["rating_at_schedule"] == "LOW"

    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "APPROVED"
    assert_instant_equals(respondent["last_approved_at"], "2026-08-13T00:00:00Z")
    assert respondent["approved_risk_rating"] == "LOW"
    assert_instant_equals(respondent["refresh_due_date"], "2029-08-13T00:00:00Z")


def _observation_scenario():
    """Approved LOW respondent with one CALIBRATED profile whose DE corridor carries a
    1560000.00 dollar threshold and a 63 count threshold."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    rid = _approved_low(
        code, legal_name="Bremen Aussenbank AG", expected_monthly_volume_usd=1000000.00,
        expected_monthly_count=40,
    )
    profile = open_profile(
        rid, [corridor(code, 1000000.00, 40)], tolerance_pct=0.20,
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z",
    )
    calibrate(profile["id"])
    calibrated = read_profile(profile["id"])
    assert calibrated["calibration_state"] == "CALIBRATED"
    assert calibrated["corridor_thresholds"] == [
        {"jurisdiction_code": code, "usd_threshold": 1560000.00, "count_threshold": 63}
    ]
    assert calibrated["aggregate_usd_threshold"] == 1716000.00
    assert calibrated["hold_threshold_usd"] == 171600.00
    return code, rid, profile


def test_calibrated_profile_raises_both_the_volume_and_the_count_breach(api):
    """Against a CALIBRATED parent the observation raises exactly two alerts, in the
    pinned VOLUME_BREACH-then-COUNT_BREACH order, with the volume severity taken from the
    observation's own ratio and the count severity from the doubling test.

    Design: Difficulty/cross_entity_state_dependency/volume_and_count_alerts_are_suppressed_by_the_parent_profile_state_while_ratios_and_the_nested_signal_survive
    """
    code, rid, profile = _observation_scenario()

    observation = post_observation(
        profile["id"], "2026-07", code, aggregate_usd=5000000.00, txn_count=130,
        distinct_downstream_count=0,
    )

    assert observation["alerts_created_count"] == 2
    assert observation["usd_threshold_applied"] == 1560000.00
    assert observation["count_threshold_applied"] == 63
    assert observation["breach_ratio"] == 3.2051  # round(5000000.00/1560000.00, 4)

    alerts = alerts_for(rid)
    assert [(a["alert_type"], a["severity"], a["breach_ratio"]) for a in alerts] == [
        ("VOLUME_BREACH", "CRITICAL", 3.2051),  # 3.2051 >= 3.0000
        ("COUNT_BREACH", "HIGH", None),  # 130 >= 2*63
    ]


def test_recalibration_required_suppresses_the_breaches_but_not_the_nested_signal(api):
    """REQUIRE_RECALIBRATION retains the corridor thresholds, so the identical payload
    still writes the same three numeric fields, yet only the undisclosed-nesting alert
    survives - the volume and count breaches are gated on `calibration_state` alone.

    Design: Difficulty/cross_entity_state_dependency/volume_and_count_alerts_are_suppressed_by_the_parent_profile_state_while_ratios_and_the_nested_signal_survive
    """
    code, rid, profile = _observation_scenario()
    post_observation(
        profile["id"], "2026-07", code, aggregate_usd=5000000.00, txn_count=130,
        distinct_downstream_count=0,
    )

    flagged = validate_success(
        api.calibrate_profile(
            profile["id"],
            {"action": "REQUIRE_RECALIBRATION", "recalibration_reason": "OFFICER_ACTION"},
            ANALYST,
        )
    )
    assert flagged["calibration_state"] == "RECALIBRATION_REQUIRED"
    assert flagged["recalibration_reason"] == "OFFICER_ACTION"
    assert flagged["corridor_thresholds"] == [
        {"jurisdiction_code": code, "usd_threshold": 1560000.00, "count_threshold": 63}
    ]
    assert flagged["aggregate_usd_threshold"] == 1716000.00
    assert flagged["hold_threshold_usd"] == 171600.00

    second = post_observation(
        profile["id"], "2026-08", code, aggregate_usd=5000000.00, txn_count=130,
        distinct_downstream_count=1,
    )

    assert second["alerts_created_count"] == 1
    assert second["usd_threshold_applied"] == 1560000.00
    assert second["count_threshold_applied"] == 63
    assert second["breach_ratio"] == 3.2051  # unchanged by the calibration state

    alerts = alerts_for(rid)
    assert len(alerts) == 3
    assert alerts[2]["alert_type"] == "NESTED_ACTIVITY_UNDISCLOSED"  # 1 > known 0, strict
    assert alerts[2]["severity"] == "CRITICAL"  # nested_activity_permitted is false
    assert alerts[2]["breach_ratio"] is None

    respondent = read_respondent(rid)
    assert respondent["risk_rating"] == "LOW"
    assert respondent["dd_state"] == "APPROVED"
