"""Treatment plan lifecycle: activation gated on authorization state, creation
referential guards, completion blocked by open sessions, and evaluation-finalize
terminal lockdown.

Queue A: cross_plan_activation_requires_auth_approved.
Queue B: error_evaluation_not_finalized_on_plan, error_evaluation_patient_mismatch_on_plan,
error_open_sessions_block_plan_completion, finalize_already_finalized_evaluation.
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    get_success_data,
    create_patient,
    create_draft_evaluation,
    create_finalized_evaluation,
    create_authorization,
    create_plan,
    create_treatment_plan_payload,
    setup_scheduled_session_scenario,
)

CLINICIAN = TEST_USERS["clinician_headers"]
AUTHORIZER = TEST_USERS["authorizer_headers"]


def _submitted_authorization(patient_id, **over):
    auth = create_authorization(patient_id, **over)
    get_success_data(api_client.submit_authorization(auth["id"], AUTHORIZER))
    return auth


# ---- Queue A: cross_plan_activation_requires_auth_approved (>=2 tests) ----

def test_activation_rejected_when_auth_not_approved(api):
    """PRD §3.4: "Activation is a Clinician action that requires the plan to be in DRAFT
    (otherwise ERR_INVALID_STATE) and the referenced authorization to be APPROVED
    (otherwise ERR_AUTH_NOT_APPROVED); it advances the plan DRAFT → ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cross_plan_activation_requires_auth_approved
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(patient["id"], body_region="LEFT_ARM")
    auth = _submitted_authorization(patient["id"], body_region="LEFT_ARM", visit_cap=5)
    plan = create_plan(patient["id"], evaluation["id"], auth["id"])
    validate_error(api.activate_treatment_plan(plan["id"], CLINICIAN), ApiErrorId.ERR_AUTH_NOT_APPROVED)


def test_plan_stays_draft_when_activation_rejected(api):
    """PRD §3.4: "Activation ... requires ... the referenced authorization to be APPROVED
    (otherwise ERR_AUTH_NOT_APPROVED); it advances the plan DRAFT → ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cross_plan_activation_requires_auth_approved
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(patient["id"], body_region="LEFT_ARM")
    auth = _submitted_authorization(patient["id"], body_region="LEFT_ARM", visit_cap=5)
    plan = create_plan(patient["id"], evaluation["id"], auth["id"])
    api.activate_treatment_plan(plan["id"], CLINICIAN)
    still = get_success_data(api.get_treatment_plan(plan["id"], CLINICIAN))
    assert still["status"] == "DRAFT"


# ---- Queue B: plan create referential/state guards ----

def test_plan_create_rejected_when_evaluation_not_finalized(api):
    """PRD §3.4: "The referenced evaluation must be FINALIZED — a still-DRAFT evaluation
    is rejected with ERR_EVALUATION_NOT_FINALIZED — and must belong to the named patient,
    else ERR_EVALUATION_PATIENT_MISMATCH."

    Design: Corner/validations/error_evaluation_not_finalized_on_plan
    """
    patient = create_patient()
    evaluation = create_draft_evaluation(patient["id"], body_region="LEFT_ARM")
    auth = create_authorization(patient["id"], body_region="LEFT_ARM", visit_cap=5)
    payload = create_treatment_plan_payload(patient["id"], evaluation["id"], auth["id"])
    validate_error(api.create_treatment_plan(payload, CLINICIAN), ApiErrorId.ERR_EVALUATION_NOT_FINALIZED)


def test_plan_create_rejected_on_evaluation_patient_mismatch(api):
    """PRD §3.4: "The referenced evaluation must be FINALIZED ... and must belong to the
    named patient, else ERR_EVALUATION_PATIENT_MISMATCH."

    Design: Corner/validations/error_evaluation_patient_mismatch_on_plan
    """
    patient_a = create_patient()
    eval_a = create_finalized_evaluation(patient_a["id"], body_region="LEFT_ARM")
    patient_b = create_patient()
    auth_b = create_authorization(patient_b["id"], body_region="LEFT_ARM", visit_cap=5)
    payload = create_treatment_plan_payload(patient_b["id"], eval_a["id"], auth_b["id"])
    validate_error(api.create_treatment_plan(payload, CLINICIAN), ApiErrorId.ERR_EVALUATION_PATIENT_MISMATCH)


def test_plan_completion_blocked_by_open_session(api):
    """PRD §3.4: "Completing a plan is a Clinician action requiring the plan to be ACTIVE
    (otherwise ERR_INVALID_STATE) and requiring that no session on the plan is still in
    clinical_status SCHEDULED or CHECKED_IN; an attempt to complete with open sessions is
    rejected with ERR_OPEN_SESSIONS_EXIST."

    Design: Corner/validations/error_open_sessions_block_plan_completion
    """
    s = setup_scheduled_session_scenario(visit_cap=5)
    validate_error(api.complete_treatment_plan(s["plan"]["id"], CLINICIAN), ApiErrorId.ERR_OPEN_SESSIONS_EXIST)


def test_finalize_already_finalized_evaluation_invalid_state(api):
    """PRD §3.2: "A Clinician finalizes it, which requires the evaluation to be in DRAFT
    and otherwise returns ERR_INVALID_STATE."

    Design: Corner/state_machines/finalize_already_finalized_evaluation_returns_invalid_state
    """
    patient = create_patient()
    evaluation = create_finalized_evaluation(patient["id"], body_region="LEFT_ARM")
    validate_error(api.finalize_evaluation(evaluation["id"], CLINICIAN), ApiErrorId.ERR_INVALID_STATE)
