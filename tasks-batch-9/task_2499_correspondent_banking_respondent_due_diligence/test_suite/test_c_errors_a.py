"""Corner queue - section errors, part A: per-family 404 codes and child-state refusals."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_nested,
    licensed_respondent,
    new_jurisdiction,
    open_questionnaire,
    progress_refresh,
    read_nested,
    read_refresh,
    read_respondent,
    schedule_refresh,
    setup_approved_respondent,
    setup_restricted_respondent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, RM


def _de():
    return new_jurisdiction(
        jurisdiction_code="DE", name="Germany", basel_aml_index=4.0, corridor_risk_weight=1.0
    )


def _licensed():
    _de()
    return licensed_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )


def test_every_child_path_id_has_its_own_not_found_code(api):
    """Nine sibling families each answer with their own not-found code, so the code is chosen
    by which path parameter failed to resolve rather than by a single shared default.

    Design: Corner/errors/every_child_path_id_has_its_own_not_found_code
    """
    cases = [
        (api.get_questionnaire, ApiErrorId.ERR_QUESTIONNAIRE_NOT_FOUND),
        (api.get_control_assessment, ApiErrorId.ERR_CONTROL_ASSESSMENT_NOT_FOUND),
        (api.get_activity_observation, ApiErrorId.ERR_ACTIVITY_OBSERVATION_NOT_FOUND),
        (api.get_monitoring_alert, ApiErrorId.ERR_MONITORING_ALERT_NOT_FOUND),
        (api.get_information_request, ApiErrorId.ERR_INFORMATION_REQUEST_NOT_FOUND),
        (api.get_adverse_media_event, ApiErrorId.ERR_ADVERSE_MEDIA_EVENT_NOT_FOUND),
        (api.get_periodic_refresh, ApiErrorId.ERR_PERIODIC_REFRESH_NOT_FOUND),
        (api.get_payment_instruction, ApiErrorId.ERR_PAYMENT_INSTRUCTION_NOT_FOUND),
        (api.get_closure_plan, ApiErrorId.ERR_CLOSURE_PLAN_NOT_FOUND),
    ]

    request_ids = []
    for getter, expected in cases:
        response = getter(NON_EXISTENT_UUID, ANALYST)
        validate_error(response, expected, expected_status=404)
        meta = response.json()["meta"]
        assert meta["api_request_id"].startswith("req_")
        assert meta["api_request_timestamp"]
        request_ids.append(meta["api_request_id"])

    assert len(set(request_ids)) == len(cases)


def test_assessing_a_draft_questionnaire_is_a_child_state_error(api):
    """The questionnaire fails the state rung and the completeness rung at once, and the lower
    priority number has to win, so nothing about the score is even looked at.

    Design: Corner/errors/assessing_a_draft_questionnaire_is_a_child_state_error
    """
    respondent = _licensed()
    questionnaire = open_questionnaire(respondent["id"])
    assert questionnaire["state"] == "DRAFT"

    response = api.decide_assessment(
        questionnaire["id"], {"action": "ASSESS", "variant": "ONBOARDING_PROVISIONAL"}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_INVALID_QUESTIONNAIRE_STATE, expected_status=409)

    stored = validate_success(api.get_questionnaire(questionnaire["id"], ANALYST))
    assert stored["state"] == "DRAFT"
    assert stored["computed_control_score"] is None
    assert read_respondent(respondent["id"])["control_score"] == 0.00


def test_reverting_a_disclosed_nested_row_is_a_child_state_error(api):
    """A row that was never confirmed has nothing to revert, so the rollup must not be re-run
    behind the refusal.

    Design: Corner/errors/reverting_a_disclosed_nested_row_is_a_child_state_error
    """
    respondent = _licensed()
    row = add_nested(
        respondent["id"], "DE", downstream_institution_name="Downstream Institution",
        discovery_source="QUESTIONNAIRE",
    )
    assert row["state"] == "DISCLOSED"
    units_before = read_respondent(respondent["id"])["nested_exposure_units"]

    response = api.adjudicate_nested(row["id"], {"action": "REVERT"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_NESTED_STATE, expected_status=409)

    stored = read_nested(row["id"])
    assert stored["state"] == "DISCLOSED"
    assert stored["adjudicated_by_user_id"] is None
    assert read_respondent(respondent["id"])["nested_exposure_units"] == units_before


def test_completing_a_scheduled_refresh_cycle_is_a_child_state_error(api):
    """Skipping the start of the cycle fails the declared-transition rung, which is evaluated
    before the endpoint's own reassessment gate that this cycle would also fail.

    Design: Corner/errors/completing_a_scheduled_refresh_cycle_is_a_child_state_error
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    cycle = schedule_refresh(rid, "2026-08-01T00:00:00Z", "2026-10-30T00:00:00Z")
    assert cycle["state"] == "SCHEDULED"
    assert read_respondent(rid)["dd_state"] == "REFRESH_DUE"

    response = api.progress_refresh(cycle["id"], {"action": "COMPLETE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_INVALID_REFRESH_STATE, expected_status=409)

    stored = read_refresh(cycle["id"])
    assert stored["state"] == "SCHEDULED"
    assert stored["completed_at"] is None
    assert read_respondent(rid)["dd_state"] == "REFRESH_DUE"


def test_completing_an_in_progress_refresh_without_a_refresh_final_assessment(api):
    """With the cycle legally under way the declared transition is satisfied, so the endpoint's
    own gate becomes the failing one and the respondent stays under refresh.

    Design: Corner/errors/completing_an_in_progress_refresh_without_a_refresh_final_assessment
    """
    _de()
    bundle = setup_approved_respondent(
        "DE", legal_name="Nordbank AG", swift_bic="NORDDEFF",
        expected_monthly_volume_usd=500000.00, expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    last_approved_at = read_respondent(rid)["last_approved_at"]
    cycle = schedule_refresh(rid, "2026-08-01T00:00:00Z", "2026-10-30T00:00:00Z")
    started = progress_refresh(cycle["id"], "START")
    assert started["state"] == "IN_PROGRESS"
    assert read_respondent(rid)["dd_state"] == "UNDER_REFRESH"
    assert read_respondent(rid)["risk_assessment_variant"] == "ONBOARDING_PROVISIONAL"

    response = api.progress_refresh(cycle["id"], {"action": "COMPLETE"}, ANALYST)
    validate_error(response, ApiErrorId.ERR_REFRESH_NOT_REASSESSED, expected_status=422)

    stored = read_refresh(cycle["id"])
    assert stored["state"] == "IN_PROGRESS"
    assert stored["completed_at"] is None
    assert stored["completed_control_score"] is None
    assert stored["completion_risk_rating"] is None
    respondent = read_respondent(rid)
    assert respondent["dd_state"] == "UNDER_REFRESH"
    assert respondent["last_approved_at"] == last_approved_at


def test_submitting_a_payment_while_the_posture_is_blocked(api):
    """The posture rung sits above the screening ladder, so no instruction row is created at
    all and there is never a screening state to inspect.

    Design: Corner/errors/submitting_a_payment_while_the_posture_is_blocked
    """
    _de()
    bundle = setup_restricted_respondent(
        "OFFICER_ACTION", jurisdiction_code="DE", legal_name="Nordbank AG",
        swift_bic="NORDDEFF", expected_monthly_volume_usd=500000.00,
        expected_monthly_count=100,
    )
    rid = bundle["respondent"]["id"]
    assert bundle["respondent"]["payment_posture"] == "BLOCKED"

    response = api.create_payment_instruction(
        rid,
        {"ordering_jurisdiction_code": "DE", "beneficiary_jurisdiction_code": "DE",
         "amount_usd": 1000.00, "purpose_code": "INTERBANK_PLACEMENT"},
        RM,
    )
    validate_error(
        response, ApiErrorId.ERR_RESPONDENT_PAYMENT_POSTURE_BLOCKED, expected_status=403
    )

    _rows, meta = validate_paginated(
        api.list_payment_instructions(RM, params={"respondent_bank_id": rid})
    )
    assert meta["total_count"] == 0
