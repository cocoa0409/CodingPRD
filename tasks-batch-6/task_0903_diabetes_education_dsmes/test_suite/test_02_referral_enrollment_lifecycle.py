"""Referral intake, assessment, and enrollment creation/activation gates.

Queue A (Difficulty): cross_entity_state_dependency.
Queue B (Corner): state_machines + validations on the referral/enrollment pipeline.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_active_enrollment, make_enrollment,
    create_enrollment_payload, make_dietitian_headers,
)
import test_helpers as th

COORD = TEST_USERS["coordinator_headers"]


# --- Queue A: ce_enrollment_requires_referral_assessed ---
def test_enrollment_from_received_referral_rejected(api):
    """PRD §3.3: "The referral must be in `ASSESSED`; a create against a referral
    in any other state is rejected with `ERR_REFERRAL_NOT_ASSESSED`."

    Design: Difficulty/cross_entity_state_dependency/ce_enrollment_requires_referral_assessed
    """
    ctx = setup_active_enrollment(api, assess=False, create_enrollment=False)
    resp = api.create_enrollment(
        create_enrollment_payload(ctx["referral_id"], ctx["curriculum_id"]), COORD
    )
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_ASSESSED.value)


def test_enrollment_succeeds_once_referral_assessed(api):
    """PRD §3.3: "The referral must be in `ASSESSED`; a create against a referral
    in any other state is rejected with `ERR_REFERRAL_NOT_ASSESSED`."

    Control: with the referral moved to ASSESSED the same create now succeeds,
    proving the gate is the referral state, not some other condition.

    Design: Difficulty/cross_entity_state_dependency/ce_enrollment_requires_referral_assessed
    """
    ctx = setup_active_enrollment(api, assess=True, create_enrollment=False)
    created = validate_success(
        api.create_enrollment(create_enrollment_payload(ctx["referral_id"], ctx["curriculum_id"]), COORD), 201
    )
    assert created["status"] == "PENDING", f"new enrollment must be PENDING, got {created['status']}"


# --- Queue A: ce_session_requires_enrollment_active ---
def test_schedule_session_on_pending_enrollment_rejected(api):
    """PRD §3.4: "The enrollment must be `ACTIVE`, or the request is rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/ce_session_requires_enrollment_active
    """
    ctx = setup_active_enrollment(api, create_enrollment=True, activate=False)
    resp = th.schedule_individual_session(
        api, ctx, "2026-05-19T09:00:00Z", "2026-05-19T10:00:00Z",
        expected_version=ctx["enrollment_version"],
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_schedule_session_succeeds_after_activation(api):
    """PRD §3.4: "The enrollment must be `ACTIVE`, or the request is rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE`."

    Control: once the same enrollment is activated the identical schedule
    succeeds, isolating the enrollment-active gate.

    Design: Difficulty/cross_entity_state_dependency/ce_session_requires_enrollment_active
    """
    ctx = setup_active_enrollment(api, activate=True)
    session = th.schedule_individual_session_ok(
        api, ctx, "2026-05-19T09:00:00Z", "2026-05-19T10:00:00Z"
    )
    assert session["encounter_status"] == "SCHEDULED", \
        f"scheduled session must be SCHEDULED, got {session['encounter_status']}"


# --- Queue B corner instances ---
def test_assess_already_assessed_referral_rejected(api):
    """PRD §3.2: "The accreditation-required assessment is a clinical step
    performed by a dietitian on a referral that is still in `RECEIVED`; attempting
    it from any other state fails with `ERR_REFERRAL_INVALID_STATE`."

    Design: Corner/state_machines/sm_referral_assess_from_assessed_rejected
    """
    ctx = setup_active_enrollment(api, assess=True, create_enrollment=False)
    resp = api.assess_referral(
        ctx["referral_id"], {"assessed_a1c": 7.9}, make_dietitian_headers(ctx["dietitian_id"])
    )
    validate_error(resp, ApiErrorId.ERR_REFERRAL_INVALID_STATE.value)


def test_reinstate_active_enrollment_rejected(api):
    """PRD §3.3: "Reinstatement returns a `SUSPENDED` enrollment to `ACTIVE`; it
    is valid only from `SUSPENDED` (else `ERR_ENROLLMENT_INVALID_STATE`)".

    Design: Corner/state_machines/sm_enrollment_reinstate_from_active_rejected
    """
    ctx = setup_active_enrollment(api, activate=True)
    resp = api.reinstate_enrollment(ctx["enrollment_id"], COORD)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value)


def test_activate_enrollment_on_lapsed_program_rejected(api):
    """PRD §3.3: "Activation additionally requires the governing program to be
    `ACCREDITED`; if the program's `accreditation_status` is `PROBATION` or
    `LAPSED`, activation is refused with `ERR_PROGRAM_NOT_ACCREDITED`."

    Design: Corner/validations/val_program_not_accredited_on_activate
    """
    ctx = setup_active_enrollment(
        api, program_overrides={"accreditation_status": "LAPSED"}, create_enrollment=True, activate=False
    )
    resp = api.activate_enrollment(ctx["enrollment_id"], COORD)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_ACCREDITED.value)


def test_enrollment_curriculum_type_mismatch_rejected(api):
    """PRD §3.3: "The chosen curriculum must fit the patient: its
    `diabetes_type_focus` must be `ANY` or must equal the patient's
    `diabetes_type`, otherwise the create is rejected with
    `ERR_CURRICULUM_TYPE_MISMATCH`."

    Design: Corner/validations/val_curriculum_type_mismatch_on_enroll
    """
    ctx = setup_active_enrollment(
        api, curriculum_focus="TYPE_1", patient_type="TYPE_2", assess=True, create_enrollment=False
    )
    resp = api.create_enrollment(
        create_enrollment_payload(ctx["referral_id"], ctx["curriculum_id"]), COORD
    )
    validate_error(resp, ApiErrorId.ERR_CURRICULUM_TYPE_MISMATCH.value)
