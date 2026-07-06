"""State-machine tests: cyclic transitions, invalid transitions, precondition
violations, and compensation. Pinned to PRD §3.2, §3.4, §3.5, §3.8, §3.9.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    fixtures, factories, ApiErrorId,
    make_wound_clinician_headers, make_hyperbaric_tech_headers,
)


# =============================================================================
# non_linear_state_machine — cyclic loops (queue A)
# =============================================================================

def test_prior_auth_resubmission_cycle_then_approve(api):
    """PRD §3.5: "From SUBMITTED, the liaison may request additional information,
    moving the authorization to ADDITIONAL_INFO_REQUESTED and setting its
    info_request_note". PRD §3.5: "From ADDITIONAL_INFO_REQUESTED, the liaison
    resubmits, returning the authorization to SUBMITTED". PRD §3.5: "Approving
    moves the authorization to APPROVED and, as cross-entity effects, flips the
    plan's coverage_status to COVERED".
    An auth cycles SUBMITTED -> ADDITIONAL_INFO_REQUESTED -> SUBMITTED, then is
    APPROVED; plan coverage becomes COVERED.

    Design: Difficulty/non_linear_state_machine/prior_auth_resubmission_cycle
    """
    base = fixtures.setup_draft_plan(budget_cents=100000, mrn="M5", accept_into_care=False)
    auth = validate_success(api.create_prior_authorization(
        factories.create_prior_authorization_payload(
            base["plan_id"], requested_hbo_sessions=3), fixtures.PAYER), 201)
    validate_success(api.request_info_prior_authorization(
        auth["id"], {"info_request_note": "send TcPO2 study"}, fixtures.PAYER))
    validate_success(api.resubmit_prior_authorization(auth["id"], fixtures.PAYER))
    approved = validate_success(api.approve_prior_authorization(auth["id"], fixtures.PAYER))
    assert approved["status"] == "APPROVED"
    plan = validate_success(api.get_treatment_plan(
        base["plan_id"], make_wound_clinician_headers(base["wc_id"])))
    assert plan["coverage_status"] == "COVERED"


def test_prior_auth_resubmit_requires_awaiting_info_state(api):
    """PRD §3.5: "a resubmit on an authorization not in ADDITIONAL_INFO_REQUESTED
    fails with ERR_AUTH_NOT_AWAITING_INFO."
    A freshly-SUBMITTED auth cannot be resubmitted.

    Design: Difficulty/non_linear_state_machine/prior_auth_resubmission_cycle
    """
    base = fixtures.setup_draft_plan(budget_cents=100000, mrn="M5b", accept_into_care=False)
    auth = validate_success(api.create_prior_authorization(
        factories.create_prior_authorization_payload(base["plan_id"]), fixtures.PAYER), 201)
    resp = api.resubmit_prior_authorization(auth["id"], fixtures.PAYER)
    validate_error(resp, ApiErrorId.ERR_AUTH_NOT_AWAITING_INFO.value)


def test_treatment_plan_suspend_resume_cycle(api):
    """PRD §3.4: "An ACTIVE plan may be suspended, moving it to SUSPENDED".
    PRD §3.4: "A SUSPENDED plan may be resumed back to ACTIVE, permitted only
    when the plan is SUSPENDED (otherwise ERR_PLAN_NOT_SUSPENDED) and the patient
    is IN_CARE".
    A plan cycles ACTIVE -> SUSPENDED -> ACTIVE via suspend then resume.

    Design: Difficulty/non_linear_state_machine/treatment_plan_suspend_resume_cycle
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M6")
    wc_id = base["wc_id"]
    validate_success(api.suspend_treatment_plan(base["plan_id"], make_wound_clinician_headers(wc_id)))
    resumed = validate_success(api.resume_treatment_plan(
        base["plan_id"], make_wound_clinician_headers(wc_id)))
    assert resumed["status"] == "ACTIVE"


def test_treatment_plan_resume_from_active_rejected(api):
    """PRD §3.4: "A SUSPENDED plan may be resumed back to ACTIVE, permitted only
    when the plan is SUSPENDED (otherwise ERR_PLAN_NOT_SUSPENDED)".
    Resuming a plan still in ACTIVE is rejected; no state change.

    Design: Difficulty/non_linear_state_machine/treatment_plan_suspend_resume_cycle
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="M6b")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    resp = api.resume_treatment_plan(base["plan_id"], wc_headers)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_SUSPENDED.value)
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["status"] == "ACTIVE"


# =============================================================================
# Corner: state_machines section
# =============================================================================

def test_resume_from_active_plan_returns_not_suspended(api):
    """PRD §3.4: "A SUSPENDED plan may be resumed back to ACTIVE, permitted only
    when the plan is SUSPENDED (otherwise ERR_PLAN_NOT_SUSPENDED)".
    Resume on an ACTIVE plan returns ERR_PLAN_NOT_SUSPENDED; status stays ACTIVE.

    Design: Corner/state_machines/resume_from_active_plan_returns_not_suspended
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="Mres")
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    resp = api.resume_treatment_plan(base["plan_id"], wc_headers)
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_SUSPENDED.value)
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["status"] == "ACTIVE"


def test_double_cancel_hbo_session_returns_not_scheduled(api):
    """PRD §3.8: "A SCHEDULED session may instead be cancelled to CANCELLED (a
    cancel on a session not in SCHEDULED fails with ERR_SESSION_NOT_SCHEDULED);
    cancellation releases the chamber slot by decrementing occupied_slot_count by
    one".
    Cancelling an already-CANCELLED session returns ERR_SESSION_NOT_SCHEDULED and
    the chamber slot count does not go negative.

    Design: Corner/state_machines/double_cancel_hbo_session_returns_not_scheduled
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="Mdc")
    ht_id = base["ht_id"]
    sess = fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], ht_id)
    validate_success(api.cancel_hbo_session(sess["id"], make_hyperbaric_tech_headers(ht_id)))
    resp = api.cancel_hbo_session(sess["id"], make_hyperbaric_tech_headers(ht_id))
    validate_error(resp, ApiErrorId.ERR_SESSION_NOT_SCHEDULED.value)
    chamber = validate_success(api.get_chamber(base["chamber_id"], fixtures.INTAKE))
    assert chamber["occupied_slot_count"] == 0, \
        f"slot count must not go negative, got {chamber['occupied_slot_count']}"


def test_activate_non_draft_plan_returns_not_draft(api):
    """PRD §3.4: "Activation moves a plan from DRAFT to ACTIVE. It is permitted
    only when the plan is in DRAFT (otherwise ERR_PLAN_NOT_DRAFT)".
    Activating an already-ACTIVE plan returns ERR_PLAN_NOT_DRAFT.

    Design: Corner/state_machines/activate_non_draft_plan_returns_not_draft
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="Mand")
    resp = api.activate_treatment_plan(
        base["plan_id"], make_wound_clinician_headers(base["wc_id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT.value)


def test_referral_accept_without_assessment_returns_error(api):
    """PRD §3.2: "Acceptance additionally requires that at least one
    WoundAssessment already exists on file for the patient, without which the
    accept is rejected with ERR_NO_ASSESSMENT_ON_FILE."
    Accepting a referral for a patient with zero assessments returns
    ERR_NO_ASSESSMENT_ON_FILE; patient stays INTAKE.

    Design: Corner/state_machines/referral_accept_without_assessment_returns_error
    """
    base = fixtures.setup_center_staff_patient(mrn="Mnoa")
    ref = validate_success(api.create_referral(
        factories.create_referral_payload(base["patient_id"]), fixtures.INTAKE), 201)
    resp = api.accept_referral(ref["id"], fixtures.INTAKE)
    validate_error(resp, ApiErrorId.ERR_NO_ASSESSMENT_ON_FILE.value)
    patient = validate_success(api.get_patient(base["patient_id"], fixtures.INTAKE))
    assert patient["status"] == "INTAKE"


def test_outcome_report_with_open_session_returns_error(api):
    """PRD §3.10: "Closing is permitted only when the plan is in ACTIVE or
    SUSPENDED (otherwise ERR_PLAN_NOT_CLOSEABLE) and no HBO session for the plan
    remains in SCHEDULED status (otherwise ERR_OPEN_SESSIONS_EXIST)."
    Closing a plan while a SCHEDULED session remains returns
    ERR_OPEN_SESSIONS_EXIST; plan not CLOSED.

    Design: Corner/state_machines/outcome_report_with_open_session_returns_error
    """
    base = fixtures.setup_active_covered_plan_with_chamber(mrn="Mopen")
    fixtures.schedule_hbo_session(base["plan_id"], base["chamber_id"], base["ht_id"])
    wc_headers = make_wound_clinician_headers(base["wc_id"])
    resp = api.outcome_report_treatment_plan(base["plan_id"], wc_headers)
    validate_error(resp, ApiErrorId.ERR_OPEN_SESSIONS_EXIST.value)
    plan = validate_success(api.get_treatment_plan(base["plan_id"], wc_headers))
    assert plan["status"] == "ACTIVE"


def test_transfer_cancel_reverts_patient_to_in_care(api):
    """PRD §3.9: "A still-unaccepted transfer may be cancelled, moving it from
    INITIATED to CANCELLED and reverting the patient's status from TRANSFERRED
    back to IN_CARE".
    Cancelling an INITIATED transfer reverts the patient to IN_CARE.

    Design: Corner/state_machines/transfer_cancel_reverts_patient_to_in_care
    """
    base = fixtures.setup_active_plan(budget_cents=100000, mrn="Mtc")
    transfer = fixtures.initiate_transfer(base["patient_id"])
    cancelled = validate_success(api.cancel_acute_transfer(
        transfer["id"], fixtures.ATTENDING))
    assert cancelled["status"] == "CANCELLED"
    patient = validate_success(api.get_patient(base["patient_id"], fixtures.INTAKE))
    assert patient["status"] == "IN_CARE"
