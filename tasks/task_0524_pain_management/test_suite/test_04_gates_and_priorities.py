"""Safety gates, cross-entity preconditions, and validation-priority conflicts on the
prescription-activate and procedure-schedule paths.

Queue A: cross_entity_state_dependency, priority_pair_validation_conflict.
Queue B: validations, endpoints, errors sections.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_prescriber_headers,
    make_compliance_officer_headers,
    setup_active_medication_patient,
    setup_active_procedure_patient,
    propose_prescription,
    activate_prescription,
    create_active_agreement,
    create_draft_agreement,
    create_pdmp_check,
    create_approved_prescription_pa,
    submit_prescription_pa,
    create_approved_procedure_pa,
    submit_procedure_pa,
    request_procedure,
    schedule_procedure_with_current_version,
    create_active_below_threshold_rx,
    get_prescription,
    create_clinic,
    create_prescriber,
    register_patient,
    create_routed_plan,
    advance_patient_to_active,
    set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
PA_CLERK = TEST_USERS["prior_auth_clerk_headers"]


def test_activate_blocked_while_agreement_still_draft(api):
    """PRD 3.4: "the agreement is created in `DRAFT`."
    PRD 3.5: "First, an `OpioidAgreement` for the patient must be `ACTIVE` and unexpired
    (otherwise `ERR_OPIOID_AGREEMENT_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/prescription_activate_requires_agreement_active
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]

    ag = create_draft_agreement(clinic_id, patient_id, prescriber_id)  # DRAFT, not counter-signed
    create_pdmp_check(clinic_id, patient_id, prescriber_id)
    pa = create_approved_prescription_pa(clinic_id, patient_id, authorized_units=30)
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        prior_auth_id=pa["id"], drug_name="oxycodone", dose_mg=15, units_per_day=6,
        conversion_factor=1.5, day_supply=30, pills_dispensed=180,
    )
    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_OPIOID_AGREEMENT_REQUIRED.value)

    after = get_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    assert after["status"] == "PROPOSED"
    ags = validate_success(api.list_opioid_agreements(clinic_id, pres_h), 200)
    assert [a for a in ags if a["id"] == ag["id"]][0]["status"] == "DRAFT"


def test_activate_succeeds_once_agreement_active(api):
    """PRD 3.4: "Counter-signing moves the agreement from `DRAFT` to `ACTIVE`."
    PRD 3.5: "On successful activation the prescription's `provisional_daily_med_mg` is added
    to the ledger's `total_active_med_mg`, and the patient's `current_daily_med_mg` is
    recomputed."

    Design: Difficulty/cross_entity_state_dependency/prescription_activate_requires_agreement_active
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]

    create_active_agreement(clinic_id, patient_id, prescriber_id)
    create_pdmp_check(clinic_id, patient_id, prescriber_id)
    pa = create_approved_prescription_pa(clinic_id, patient_id, authorized_units=30)
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        prior_auth_id=pa["id"], drug_name="oxycodone", dose_mg=15, units_per_day=6,
        conversion_factor=1.5, day_supply=30, pills_dispensed=180,
    )
    pres_h = make_prescriber_headers(prescriber_id)
    data = validate_success(api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h), 200)
    assert data["status"] == "ACTIVE"


def test_schedule_blocked_while_prior_auth_submitted(api):
    """PRD 3.7: "The referenced `PriorAuthorization` must be `APPROVED` with `target_kind`
    `PROCEDURE` (otherwise `ERR_PRIOR_AUTH_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/procedure_schedule_requires_prior_auth_approved
    """
    ctx = setup_active_procedure_patient(modality="RFA")
    clinic_id, patient_id = ctx["clinic"]["id"], ctx["patient"]["id"]
    pa = submit_procedure_pa(clinic_id, patient_id)  # SUBMITTED, not decided
    proc = request_procedure(
        clinic_id, patient_id, ctx["plan"]["id"], ctx["suite"]["id"], pa["id"],
        start_utc="2026-06-10T10:00:00Z", duration_minutes=30,
    )
    clinic = validate_success(api.get_clinic(clinic_id, ADMIN), 200)
    resp = api.schedule_procedure(
        clinic_id, patient_id, proc["id"], {"expected_clinic_version": clinic["version"]}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_NOT_APPROVED.value)

    procs = validate_success(api.list_procedures(clinic_id, patient_id, INTAKE), 200)
    assert [p for p in procs if p["id"] == proc["id"]][0]["status"] == "REQUESTED"


# NOTE: Difficulty/priority_pair_validation_conflict/state_vs_safety_agreement_wins_on_state
# is SKIPPED. Its double-fault precondition — an above-threshold prescription in a
# non-PROPOSED state (DISCONTINUED) whose patient never held an opioid agreement — is not
# reachable under a PRD-faithful implementation: PRD 3.5 permits discontinue only from
# ACTIVE/TAPERING/SUSPENDED, and reaching ACTIVE for an above-threshold Rx requires the
# agreement gate to have been satisfied first. With no PRD-reachable setup that trips both the
# state check and the missing-agreement check simultaneously, the instance fails the
# unique-derivability / reachability filter and no faithful test can be emitted.


def test_referential_priorauth_error_preempts_fiscal_units(api):
    """PRD 2.8: "referential business checks (prior-authorization approval and target-kind
    match, treatment-plan path), then the controlled-substance safety gates ... and finally
    the fiscal authorized-units check."
    PRD 3.5: "the supplied `prior_auth_id` must reference an `APPROVED` `PriorAuthorization`
    whose `target_kind` is `PRESCRIPTION` (otherwise `ERR_PRIOR_AUTH_NOT_APPROVED`), and that
    authorization's `authorized_units` must be at least the requested `day_supply` (otherwise
    `ERR_AUTHORIZED_UNITS_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_priorauth_approval_wins
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]

    create_active_agreement(clinic_id, patient_id, prescriber_id)
    create_pdmp_check(clinic_id, patient_id, prescriber_id)
    pa = submit_prescription_pa(clinic_id, patient_id, authorized_units=1)  # SUBMITTED, units 1 < 30
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        prior_auth_id=pa["id"], drug_name="oxycodone", dose_mg=15, units_per_day=6,
        conversion_factor=1.5, day_supply=30, pills_dispensed=180,
    )
    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_PRIOR_AUTH_NOT_APPROVED.value)
    after = get_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    assert after["status"] == "PROPOSED"


def test_pdmp_check_required_when_missing(api):
    """PRD 3.5: "Second, a fresh `PdmpCheck` must exist for the patient ... (otherwise
    `ERR_PDMP_CHECK_REQUIRED`)."

    Design: Corner/validations/pdmp_required_when_agreement_present_but_no_check
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]

    create_active_agreement(clinic_id, patient_id, prescriber_id)
    pa = create_approved_prescription_pa(clinic_id, patient_id, authorized_units=30)
    # No PDMP check.
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        prior_auth_id=pa["id"], drug_name="oxycodone", dose_mg=15, units_per_day=6,
        conversion_factor=1.5, day_supply=30, pills_dispensed=180,
    )
    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_PDMP_CHECK_REQUIRED.value)


def test_discharge_blocked_by_active_prescription(api):
    """PRD 3.10: "Discharge is blocked while any prescription for the patient is still
    `ACTIVE` or `SUSPENDED` (otherwise `ERR_ACTIVE_PRESCRIPTIONS_EXIST`)."

    Design: Corner/validations/discharge_blocked_by_active_prescription
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    create_active_below_threshold_rx(ctx)

    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.discharge_patient(clinic_id, patient_id, pres_h)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_PRESCRIPTIONS_EXIST.value)
    after = validate_success(api.get_patient(clinic_id, patient_id, pres_h), 200)
    assert after["status"] == "ACTIVE"


def test_taper_step_out_of_range_rejected(api):
    """PRD 3.5: "requires `taper_step_pct` to be present and strictly greater than 0 and at
    most 100 (otherwise `ERR_TAPER_STEP_INVALID`)."

    Design: Corner/validations/taper_step_out_of_range_rejected
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = create_active_below_threshold_rx(ctx, taper_step_pct=150)  # 150 > 100

    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.start_taper(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_TAPER_STEP_INVALID.value)
    after = get_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    assert after["status"] == "ACTIVE"
