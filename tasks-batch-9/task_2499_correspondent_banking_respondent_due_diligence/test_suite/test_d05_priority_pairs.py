"""Difficulty queue - rule priority_pair_validation_conflict.

The declared precedence pairs P1 (priority 14 state beats priority 41 fiscal) and P3
(priority 37 constraint beats priority 42 fiscal), each exercised by replaying one
request across a state change so that the losing check is seen to be reachable.
"""
from test_helpers import (
    ApiErrorId,
    add_control_rows,
    add_verified_owner,
    approve_plan,
    calibrate,
    committee_decision,
    corridor,
    draft_plan,
    licensed_respondent,
    new_jurisdiction,
    open_profile,
    open_questionnaire,
    read_payment,
    read_plan,
    read_profile,
    read_respondent,
    respondent_version,
    score_respondent,
    submit_payment,
    submit_plan,
    submit_questionnaire,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, OFFICER, assess_questionnaire


DOMAINS = [
    "GOVERNANCE", "KYC_ONBOARDING", "TRANSACTION_MONITORING", "SANCTIONS_SCREENING",
    "PEP_HANDLING", "TRAINING", "AUDIT", "NESTED_CONTROLS",
]

RELEASE = {"action": "RELEASE", "decision_reason": "WIND_DOWN_PERMITTED"}


def _flat_score(rid, rating=4):
    questionnaire = open_questionnaire(rid, version="V1")
    add_control_rows(questionnaire["id"], rid, {d: rating for d in DOMAINS})
    submit_questionnaire(questionnaire["id"], rid)
    assess_questionnaire(questionnaire["id"], "ONBOARDING_PROVISIONAL")
    return score_respondent(rid, "ONBOARDING_PROVISIONAL")


def _zero_cap_exit():
    """Approved LOW respondent driven into EXITING by a SANCTIONS_EXPOSURE plan whose
    notice period, and therefore whose wind-down cap, is exactly zero."""
    jp = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.00,
        max_permitted_risk_rating="HIGH",
    )
    code = jp["jurisdiction_code"]
    respondent = licensed_respondent(
        code, legal_name="Dresden Aussenbank AG", expected_monthly_volume_usd=5000000.00,
        expected_monthly_count=200,
    )
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Dresden Holding", ownership_pct=80.00)
    scored = _flat_score(rid)
    assert scored["inherent_risk_score"] == 14.00
    assert scored["residual_risk_score"] == 9.28
    assert scored["risk_rating"] == "LOW"
    committee_decision(rid, "APPROVE")
    assert read_respondent(rid)["payment_posture"] == "OPEN"

    profile = open_profile(
        rid, [corridor(code, 5000000.00, 200)], tolerance_pct=0.10,
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-12-31T00:00:00Z",
    )
    calibrate(profile["id"])
    calibrated = read_profile(profile["id"])
    assert calibrated["aggregate_usd_threshold"] == 7865000.00
    assert calibrated["hold_threshold_usd"] == 786500.00

    payment = submit_payment(
        rid, code, code, amount_usd=500000.00, purpose_code="RETURN_OF_FUNDS"
    )
    assert payment["screening_state"] == "SCREENED_CLEAR"

    plan = draft_plan(
        rid, termination_reason="SANCTIONS_EXPOSURE", cap_basis="FORWARD_PROJECTED",
        original_obligation_cents=0,
    )
    submit_plan(plan["id"])
    approved_plan = approve_plan(plan["id"])
    assert approved_plan["state"] == "APPROVED"

    exiting = read_respondent(rid)
    assert exiting["dd_state"] == "EXITING"
    assert exiting["payment_posture"] == "WIND_DOWN_ONLY"
    held = read_payment(payment["id"])
    assert held["screening_state"] == "HELD_FOR_REVIEW"
    assert held["hold_reason"] == "POSTURE_SCREEN_ONLY"

    return {"jp": jp, "code": code, "rid": rid, "plan": approved_plan, "payment": payment}


def test_wind_down_cap_is_the_only_defect_while_the_posture_is_wind_down_only(api):
    """A zero notice period gives a zero cap, so the release breaches the fiscal rule and
    nothing else: the answer is 422 ERR_WIND_DOWN_CAP_EXCEEDED, proving priority 41 is
    genuinely reachable on this request.

    Design: Difficulty/priority_pair_validation_conflict/posture_blocked_state_error_outranks_the_wind_down_cap_fiscal_error_on_the_same_release
    """
    scenario = _zero_cap_exit()
    plan = read_plan(scenario["plan"]["id"])
    assert plan["notice_period_days"] == 0  # SANCTIONS_EXPOSURE base 0, no obligation
    assert plan["wind_down_cap_usd"] == 0.00  # round(5000000.00 * (0/30.0) * 0.60, 2)

    response = api.decide_screening(scenario["payment"]["id"], RELEASE, OFFICER)
    validate_error(response, ApiErrorId.ERR_WIND_DOWN_CAP_EXCEEDED)

    payment = read_payment(scenario["payment"]["id"])
    assert payment["amount_usd"] == 500000.00  # 500000.00 > 0.00, the breach is real
    assert payment["screening_state"] == "HELD_FOR_REVIEW"
    assert payment["decided_at"] is None
    assert read_plan(scenario["plan"]["id"])["wind_down_released_usd"] == 0.00


def test_posture_blocked_state_error_outranks_the_wind_down_cap_fiscal_error(api):
    """Once the home jurisdiction is comprehensively sanctioned the identical release
    request satisfies both failing rules, and the answer must flip to the priority-14
    403 rather than staying on the priority-41 422.

    Design: Difficulty/priority_pair_validation_conflict/posture_blocked_state_error_outranks_the_wind_down_cap_fiscal_error_on_the_same_release
    """
    scenario = _zero_cap_exit()
    validate_error(
        api.decide_screening(scenario["payment"]["id"], RELEASE, OFFICER),
        ApiErrorId.ERR_WIND_DOWN_CAP_EXCEEDED,
    )

    sanctioned = validate_success(
        api.amend_jurisdiction_profile(
            scenario["jp"]["id"], {"sanctions_status": "COMPREHENSIVELY_SANCTIONED"}, OFFICER
        )
    )
    assert sanctioned["sanctions_status"] == "COMPREHENSIVELY_SANCTIONED"

    restricted = read_respondent(scenario["rid"])
    assert restricted["payment_posture"] == "BLOCKED"
    assert restricted["restriction_reason"] == "SANCTIONS_EXPOSURE"

    response = api.decide_screening(scenario["payment"]["id"], RELEASE, OFFICER)
    validate_error(response, ApiErrorId.ERR_RESPONDENT_PAYMENT_POSTURE_BLOCKED)

    # Neither refused release is booked against the cap.
    plan = read_plan(scenario["plan"]["id"])
    assert plan["wind_down_released_usd"] == 0.00
    assert plan["outstanding_obligation_cents"] == 0

    payment = read_payment(scenario["payment"]["id"])
    assert payment["screening_state"] != "RELEASED"
    assert payment["decided_at"] is None


def _overlap_scenario():
    """Respondent with one CALIBRATED profile over [2026-01-01, 2026-06-30] and a
    declared volume large enough that any second profile blows the aggregate ceiling."""
    code = new_jurisdiction(
        name="Germany", basel_aml_index=4.0, corridor_risk_weight=0.50,
        max_permitted_risk_rating="HIGH",
    )["jurisdiction_code"]
    respondent = licensed_respondent(
        code, legal_name="Hamburg Grossbank AG", expected_monthly_volume_usd=200000000.00,
        expected_monthly_count=5000,
    )
    rid = respondent["id"]
    add_verified_owner(rid, code, owner_name="Hamburg Holding", ownership_pct=80.00)
    scored = _flat_score(rid)
    assert scored["inherent_risk_score"] == 22.00  # 8.00 + 0 + 0 + min(16, 14)
    assert scored["residual_risk_score"] == 14.58  # round(22.00*0.6625, 2) half up
    assert scored["risk_rating"] == "LOW"

    first = open_profile(
        rid, [corridor(code, 1000000.00, 100)], tolerance_pct=0.10,
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-06-30T00:00:00Z",
    )
    calibrate(first["id"])
    stored = read_profile(first["id"])
    assert stored["calibration_state"] == "CALIBRATED"
    assert stored["aggregate_usd_threshold"] == 3146000.00
    assert stored["hold_threshold_usd"] == 314600.00

    version = respondent_version(rid)
    payload = {
        "effective_to": "2026-12-31T00:00:00Z",
        "tolerance_pct": 0.10,
        "expected_respondent_version": version,
        "expected_corridors": [corridor(code, 200000000.00, 5000)],
    }
    return {"code": code, "rid": rid, "first": first, "version": version, "payload": payload}


def test_touching_interval_beats_the_aggregate_ceiling_and_persists_nothing(api):
    """An `effective_from` exactly equal to the neighbour's `effective_to` is an overlap
    under closed semantics, so the create answers 409 rather than the fiscal 422 its
    corridor totals would otherwise earn - and it writes nothing, not even a version bump.

    Design: Difficulty/priority_pair_validation_conflict/interval_overlap_constraint_error_outranks_the_aggregate_ceiling_fiscal_error
    """
    scenario = _overlap_scenario()
    touching = dict(scenario["payload"], effective_from="2026-06-30T00:00:00Z")

    response = api.create_monitoring_profile(scenario["rid"], touching, ANALYST)
    validate_error(response, ApiErrorId.ERR_MONITORING_INTERVAL_OVERLAP)

    rows, _meta = validate_paginated(
        api.list_monitoring_profiles(ANALYST, params={"respondent_bank_id": scenario["rid"]})
    )
    assert len(rows) == 1  # the refused create persisted nothing
    assert rows[0]["id"] == scenario["first"]["id"]

    # The same expected_respondent_version is still current, so no version was consumed.
    assert respondent_version(scenario["rid"]) == scenario["version"]
    clear = dict(scenario["payload"], effective_from="2026-07-01T00:00:00Z")
    created = validate_success(
        api.create_monitoring_profile(scenario["rid"], clear, ANALYST), expected_status=201
    )
    assert created["calibration_state"] == "PROVISIONAL"


def test_aggregate_ceiling_surfaces_at_calibration_after_each_corridor_was_clamped(api):
    """Creation runs no fiscal check at all; only CALIBRATE does, and it refuses even
    though the single corridor was first clamped down to the 500000000.00 per-corridor
    ceiling, because the 1.10 aggregate buffer pushes the sum back over it.

    Design: Difficulty/priority_pair_validation_conflict/interval_overlap_constraint_error_outranks_the_aggregate_ceiling_fiscal_error
    """
    scenario = _overlap_scenario()
    clear = dict(scenario["payload"], effective_from="2026-07-01T00:00:00Z")
    created = validate_success(
        api.create_monitoring_profile(scenario["rid"], clear, ANALYST), expected_status=201
    )
    assert created["calibration_state"] == "PROVISIONAL"
    assert created["corridor_thresholds"] == []
    assert created["aggregate_usd_threshold"] is None
    assert created["hold_threshold_usd"] is None

    response = api.calibrate_profile(created["id"], {"action": "CALIBRATE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_AGGREGATE_THRESHOLD_EXCEEDED)

    # raw 200000000.00*1.10*1.30/0.50 = 572000000.00 -> clamped 500000000.00,
    # then round(500000000.00*1.10, 2) = 550000000.00 > 500000000.00.
    refused = read_profile(created["id"])
    assert refused["calibration_state"] == "PROVISIONAL"
    assert refused["aggregate_usd_threshold"] is None
    assert refused["hold_threshold_usd"] is None
    assert refused["calibrated_at"] is None

    neighbour = read_profile(scenario["first"]["id"])
    assert neighbour["calibration_state"] == "CALIBRATED"
    assert neighbour["aggregate_usd_threshold"] == 3146000.00
    assert neighbour["hold_threshold_usd"] == 314600.00

    respondent = read_respondent(scenario["rid"])
    assert respondent["inherent_risk_score"] == 22.00
    assert respondent["residual_risk_score"] == 14.58
    assert respondent["risk_rating"] == "LOW"
