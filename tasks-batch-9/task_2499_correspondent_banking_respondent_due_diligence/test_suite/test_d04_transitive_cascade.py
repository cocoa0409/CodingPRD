"""Difficulty queue - rule transitive_cascade.

The two multi-hop fan-outs of the specification: the five-hop alert escalation and
the officer restriction taken from UNDER_REFRESH, both of which must reach entities
several relationships away from the one the request names.
"""
from test_helpers import (
    add_control_rows,
    add_nested,
    add_verified_owner,
    adjudicate_nested,
    assert_instant_equals,
    calibrate,
    committee_decision,
    corridor,
    dispose_alert,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    progress_refresh,
    raise_alert,
    read_nested,
    read_payment,
    read_profile,
    read_refresh,
    read_respondent,
    schedule_refresh,
    score_respondent,
    submit_payment,
    submit_questionnaire,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER, assess_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]


def _score_and_approve(rid):
    questionnaire = open_questionnaire(rid, version="V1")
    add_control_rows(questionnaire["id"], rid, {d: 4 for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], rid)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    scored = score_respondent(rid, "ONBOARDING_PROVISIONAL")
    committee_decision(rid, "APPROVE")
    return scored


def _escalation_scenario():
    """Approved LOW respondent with an OPEN posture, a CALIBRATED profile, three
    payment instructions and one CRITICAL VOLUME_BREACH alert under investigation."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    respondent = licensed_respondent(
        code, legal_name="Frankfurt Korrespondenzbank AG",
        expected_monthly_volume_usd=4600000.00, expected_monthly_count=300,
    )
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Frankfurt Holding", ownership_pct=80.00)
    scored = _score_and_approve(rid)
    assert scored["inherent_risk_score"] == 14.00  # 8.00 + 0 + 0 + 6
    assert scored["control_score"] == 80.00
    assert scored["control_credit"] == 0.3375
    assert scored["residual_risk_score"] == 9.28
    assert scored["risk_rating"] == "LOW"

    approved = read_respondent(rid)
    assert approved["payment_posture"] == "OPEN"

    profile = open_profile(
        rid, [corridor(code, 4600000.00, 300)], tolerance_pct=0.10,
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z",
    )
    calibrate(profile["id"])
    calibrated = read_profile(profile["id"])
    assert calibrated["calibration_state"] == "CALIBRATED"
    assert calibrated["aggregate_usd_threshold"] == 7235800.00
    assert calibrated["hold_threshold_usd"] == 723580.00

    pay1 = submit_payment(rid, code, code, amount_usd=500000.00)
    pay2 = submit_payment(rid, code, code, amount_usd=800000.00)
    pay3 = submit_payment(rid, code, code, amount_usd=250000.00)
    assert pay1["screening_state"] == "SCREENED_CLEAR"
    assert pay2["screening_state"] == "HELD_FOR_REVIEW"
    assert pay2["hold_reason"] == "AMOUNT_THRESHOLD"
    assert pay3["screening_state"] == "SCREENED_CLEAR"

    alert = raise_alert(rid, "VOLUME_BREACH", "CRITICAL", headers=OFFICER)
    assert alert["state"] == "OPEN"
    assert alert["activity_observation_id"] is None
    dispose_alert(alert["id"], "INVESTIGATE", ANALYST)

    return {
        "code": code, "rid": rid, "profile": profile, "alert": alert,
        "pay1": pay1, "pay2": pay2, "pay3": pay3,
    }


def test_alert_escalation_dispatches_exactly_one_request_and_narrows_the_posture(api):
    """Hops one to three of the single ESCALATE call: the alert is stamped, exactly one
    information request is created and dispatched with the alert's own CRITICAL severity
    and a VOLUME_BREACH topic, and only then does the posture narrow.

    Design: Difficulty/transitive_cascade/alert_escalation_fans_out_five_hops_and_holds_only_the_screened_clear_payments
    """
    scenario = _escalation_scenario()
    alert_id = scenario["alert"]["id"]

    escalated = validate_success(api.dispose_alert(alert_id, {"action": "ESCALATE"}, ANALYST))

    assert escalated["state"] == "ESCALATED"
    assert_instant_equals(escalated["escalated_at"], "2026-08-01T00:00:00Z")

    rows, _meta = validate_paginated(
        api.list_information_requests(ANALYST, params={"monitoring_alert_id": alert_id})
    )
    assert len(rows) == 1  # one request for the alert, not one per held payment
    request = rows[0]
    assert request["request_topic"] == "ACTIVITY_EXPLANATION"
    assert request["severity"] == "CRITICAL"
    assert request["state"] == "SENT"
    assert_instant_equals(request["dispatched_at"], "2026-08-01T00:00:00Z")
    assert request["sla_hours"] == 24  # CRITICAL base, LOW rating, 0 strikes
    assert_instant_equals(request["due_at"], "2026-08-02T00:00:00Z")
    assert request["escalation_level"] == 1  # dispatch raises it to at least 1

    respondent = read_respondent(scenario["rid"])
    assert respondent["escalation_units"] == 1
    assert respondent["payment_posture"] == "SCREEN_ONLY"


def test_alert_escalation_holds_only_the_screened_clear_payments_and_flags_the_profile(api):
    """Hops four and five: the fan-out rewrites exactly the two SCREENED_CLEAR
    instructions, leaves the AMOUNT_THRESHOLD hold and its recorded threshold alone, and
    flags the profile without clearing the calibrated numbers or re-scoring the bank.

    Design: Difficulty/transitive_cascade/alert_escalation_fans_out_five_hops_and_holds_only_the_screened_clear_payments
    """
    scenario = _escalation_scenario()

    validate_success(
        api.dispose_alert(scenario["alert"]["id"], {"action": "ESCALATE"}, ANALYST)
    )

    first = read_payment(scenario["pay1"]["id"])
    assert first["screening_state"] == "HELD_FOR_REVIEW"
    assert first["hold_reason"] == "POSTURE_SCREEN_ONLY"

    third = read_payment(scenario["pay3"]["id"])
    assert third["screening_state"] == "HELD_FOR_REVIEW"
    assert third["hold_reason"] == "POSTURE_SCREEN_ONLY"

    # The row already held on the amount keeps its own reason and threshold.
    second = read_payment(scenario["pay2"]["id"])
    assert second["screening_state"] == "HELD_FOR_REVIEW"
    assert second["hold_reason"] == "AMOUNT_THRESHOLD"
    assert second["hold_threshold_applied"] == 723580.00

    profile = read_profile(scenario["profile"]["id"])
    assert profile["calibration_state"] == "RECALIBRATION_REQUIRED"
    assert profile["recalibration_reason"] == "ALERT_ESCALATION"
    assert profile["aggregate_usd_threshold"] == 7235800.00
    assert profile["hold_threshold_usd"] == 723580.00

    respondent = read_respondent(scenario["rid"])
    assert respondent["residual_risk_score"] == 9.28  # the cascade never re-scores
    assert respondent["approved_risk_rating"] == "LOW"


def _under_refresh_scenario():
    """Approved LOW respondent with two CONFIRMED nested rows, a CALIBRATED profile and
    an IN_PROGRESS cadence refresh cycle, so dd_state is UNDER_REFRESH."""
    de = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    at = new_jurisdiction(
        name="Austria", basel_aml_index=3.0, corridor_risk_weight=1.20,
        nested_correspondent_prohibited=False,
    )["jurisdiction_code"]
    respondent = licensed_respondent(
        de, legal_name="Wien Nostro Bank AG", expected_monthly_volume_usd=2000000.00,
        expected_monthly_count=150, nested_activity_permitted=True,
    )
    rid = respondent["id"]
    add_verified_owner(rid, de, owner_name="Wien Nostro Holding", ownership_pct=80.00)

    nest1 = add_nested(rid, at, downstream_institution_name="Downstream Alpha",
                       discovery_source="QUESTIONNAIRE")
    nest2 = add_nested(rid, at, downstream_institution_name="Downstream Beta",
                       discovery_source="QUESTIONNAIRE")
    assert nest1["state"] == "DISCLOSED" and nest1["depth"] == 1
    adjudicate_nested(nest1["id"], "CONFIRM")
    adjudicate_nested(nest2["id"], "CONFIRM")

    scored = _score_and_approve(rid)
    assert scored["inherent_risk_score"] == 26.00  # 8.00 + 0 + min(20, 5*2) + min(16, 6+2)
    assert scored["residual_risk_score"] == 17.23  # round(26.00*0.6625, 2)
    assert scored["risk_rating"] == "LOW"

    profile = open_profile(
        rid, [corridor(de, 2000000.00, 150)], tolerance_pct=0.10,
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z",
    )
    calibrate(profile["id"])
    calibrated = read_profile(profile["id"])
    assert calibrated["aggregate_usd_threshold"] == 3146000.00
    assert calibrated["hold_threshold_usd"] == 314600.00

    cycle = schedule_refresh(
        rid, "2026-08-01T00:00:00Z", "2026-11-01T00:00:00Z", trigger_reason="CADENCE"
    )
    progress_refresh(cycle["id"], "START")
    assert read_respondent(rid)["dd_state"] == "UNDER_REFRESH"

    return {
        "de": de, "at": at, "rid": rid, "profile": profile, "cycle": cycle,
        "nest1": nest1, "nest2": nest2,
    }


def test_officer_restriction_suspends_nested_rows_without_moving_exposure_units(api):
    """RESTRICT from UNDER_REFRESH honours the explicitly supplied BLOCKED posture and
    suspends both CONFIRMED rows, yet the rollup does not move because CONFIRMED and
    SUSPENDED share state weight 3 and suspended rows still count for the depth.

    Design: Difficulty/transitive_cascade/officer_restriction_from_under_refresh_suspends_nested_rows_without_moving_exposure_units
    """
    scenario = _under_refresh_scenario()
    before = read_respondent(scenario["rid"])
    assert before["nested_exposure_units"] == 6  # 3*1 + 3*1

    restricted = validate_success(
        api.restrict_respondent(
            scenario["rid"],
            {"action": "RESTRICT", "restriction_reason": "OFFICER_ACTION",
             "payment_posture": "BLOCKED"},
            OFFICER,
        )
    )

    assert restricted["dd_state"] == "RESTRICTED"
    assert restricted["restriction_reason"] == "OFFICER_ACTION"
    assert restricted["payment_posture"] == "BLOCKED"

    assert read_nested(scenario["nest1"]["id"])["state"] == "SUSPENDED"
    assert read_nested(scenario["nest2"]["id"])["state"] == "SUSPENDED"

    after = read_respondent(scenario["rid"])
    assert after["nested_exposure_units"] == 6
    assert after["max_nested_depth"] == 1
    assert after["undisclosed_nested_count"] == 0


def test_officer_restriction_flags_the_profile_and_leaves_the_refresh_cycle_alone(api):
    """The third hop is conditional on the suspension having happened, and it only flags:
    the calibrated numbers survive, the IN_PROGRESS cycle survives with its frozen
    cadence, and neither risk score is recomputed.

    Design: Difficulty/transitive_cascade/officer_restriction_from_under_refresh_suspends_nested_rows_without_moving_exposure_units
    """
    scenario = _under_refresh_scenario()

    validate_success(
        api.restrict_respondent(
            scenario["rid"],
            {"action": "RESTRICT", "restriction_reason": "OFFICER_ACTION",
             "payment_posture": "BLOCKED"},
            OFFICER,
        )
    )

    profile = read_profile(scenario["profile"]["id"])
    assert profile["calibration_state"] == "RECALIBRATION_REQUIRED"
    assert profile["recalibration_reason"] == "OFFICER_ACTION"
    assert profile["aggregate_usd_threshold"] == 3146000.00
    assert profile["hold_threshold_usd"] == 314600.00

    cycle = read_refresh(scenario["cycle"]["id"])
    assert cycle["state"] == "IN_PROGRESS"  # only the closure cascade cancels cycles
    assert_instant_equals(cycle["started_at"], "2026-08-01T00:00:00Z")
    assert cycle["cadence_months_applied"] == 36
    assert cycle["rating_at_schedule"] == "LOW"

    respondent = read_respondent(scenario["rid"])
    assert respondent["inherent_risk_score"] == 26.00
    assert respondent["residual_risk_score"] == 17.23
