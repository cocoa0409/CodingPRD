"""State machine transitions: cyclic UDS recollect loop, cyclic prescription taper loop,
empty-set consistent result, intake/patient/plan/agreement transitions and their
precondition guards.

Queue A: non_linear_state_machine, boundary_precision_check (uds empty-set).
Queue B: state_machines section.
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
    setup_collected_uds,
    create_active_below_threshold_rx,
    propose_prescription,
    activate_prescription,
    get_prescription,
    register_patient,
    create_clinic,
    create_prescriber,
    create_compliance_officer,
    create_routed_plan,
    advance_patient_to_active,
    create_draft_agreement,
    set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def test_uds_recollect_cycles_back_to_scheduled(api):
    """PRD 3.8: "recollection moves the screen from `RESULTED_INCONSISTENT` back to
    `SCHEDULED`, permitted only while the screen is `RESULTED_INCONSISTENT`."
    PRD 3.8: "Recollection increments the screen's `recollect_count` by one, resets its
    `detected_substances` to unset, and takes a fresh `due_utc` supplied on the request."

    Design: Difficulty/non_linear_state_machine/uds_recollect_cycle_back_to_scheduled
    """
    ctx = setup_collected_uds(expected_substances=["oxycodone"])
    clinic_id, patient_id, co_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["compliance_officer"]["id"]
    uds_id = ctx["uds"]["id"]
    co_h = make_compliance_officer_headers(co_id)

    result = validate_success(
        api.result_urine_drug_screen(clinic_id, patient_id, uds_id, {"detected_substances": []}, co_h), 200
    )
    assert result["status"] == "RESULTED_INCONSISTENT"

    recol = validate_success(
        api.recollect_urine_drug_screen(clinic_id, patient_id, uds_id, {"due_utc": "2026-06-05T00:00:00Z"}, co_h), 200
    )
    assert recol["status"] == "SCHEDULED"
    assert recol["recollect_count"] == 1
    assert recol["detected_substances"] is None


def test_prescription_taper_reescalate_cycles_back_to_active(api):
    """PRD 3.5: "Starting a taper moves an `ACTIVE` prescription to `TAPERING`."
    PRD 3.5: "Re-escalating returns a `TAPERING` prescription to `ACTIVE`, permitted only
    while the prescription is `TAPERING`."

    Design: Difficulty/non_linear_state_machine/rx_taper_reescalate_cycle
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = create_active_below_threshold_rx(ctx, taper_step_pct=10)  # provisional 20
    pres_h = make_prescriber_headers(prescriber_id)

    tapering = validate_success(api.start_taper(clinic_id, patient_id, rx["id"], pres_h), 200)
    assert tapering["status"] == "TAPERING"

    active = validate_success(api.re_escalate(clinic_id, patient_id, rx["id"], pres_h), 200)
    assert active["status"] == "ACTIVE"

    patient = validate_success(api.get_patient(clinic_id, patient_id, pres_h), 200)
    assert patient["current_daily_med_mg"] == pytest.approx(20.00, abs=0.01)


def test_uds_result_empty_expected_set_is_consistent(api):
    """PRD 3.8: "If the set of `detected_substances` equals the set of `expected_substances`,
    the screen moves from `COLLECTED` to `RESULTED_CONSISTENT` with no further effect."

    Design: Difficulty/boundary_precision_check/uds_result_empty_expected_set_is_consistent
    """
    ctx = setup_collected_uds(expected_substances=[])
    clinic_id, patient_id, co_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["compliance_officer"]["id"]
    uds_id = ctx["uds"]["id"]
    co_h = make_compliance_officer_headers(co_id)

    result = validate_success(
        api.result_urine_drug_screen(clinic_id, patient_id, uds_id, {"detected_substances": []}, co_h), 200
    )
    assert result["status"] == "RESULTED_CONSISTENT"

    patient = validate_success(api.get_patient(clinic_id, patient_id, co_h), 200)
    assert patient["compliance_flag"] == "NONE"


def test_schedule_intake_on_already_scheduled_rejected(api):
    """PRD 3.2: "Scheduling intake advances the patient from `REFERRED` to `INTAKE_SCHEDULED`.
    ... this is permitted only while the patient is in `REFERRED` status (otherwise
    `ERR_PATIENT_STATE_INVALID`)."

    Design: Corner/state_machines/schedule_intake_from_intake_scheduled_invalid
    """
    clinic = create_clinic()
    patient = register_patient(clinic["id"])
    validate_success(
        api.schedule_intake(clinic["id"], patient["id"], {"intake_utc": "2026-05-10T00:00:00Z"}, INTAKE), 200
    )
    resp = api.schedule_intake(clinic["id"], patient["id"], {"intake_utc": "2026-05-11T00:00:00Z"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_PATIENT_STATE_INVALID.value)

    after = validate_success(api.get_patient(clinic["id"], patient["id"], INTAKE), 200)
    assert after["status"] == "INTAKE_SCHEDULED"


def test_discharged_patient_cannot_be_discharged_again(api):
    """PRD 3.10: "It moves the patient from `ACTIVE` to `DISCHARGED` and requires the patient
    to be `ACTIVE` (otherwise `ERR_PATIENT_STATE_INVALID`)."

    Design: Corner/state_machines/discharged_patient_terminal_lockdown
    """
    clinic = create_clinic()
    prescriber = create_prescriber(clinic["id"])
    patient = register_patient(clinic["id"])
    create_routed_plan(clinic["id"], patient["id"], prescriber["id"], "MEDICATION")
    advance_patient_to_active(clinic["id"], patient["id"])

    pres_h = make_prescriber_headers(prescriber["id"])
    validate_success(api.discharge_patient(clinic["id"], patient["id"], pres_h), 200)

    resp = api.discharge_patient(clinic["id"], patient["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_PATIENT_STATE_INVALID.value)
    after = validate_success(api.get_patient(clinic["id"], patient["id"], pres_h), 200)
    assert after["status"] == "DISCHARGED"


def test_complete_intake_before_due_rejected(api):
    """PRD 3.2: "requires that the clinic's `current_utc` has reached or passed the patient's
    `intake_utc` — that is, `current_utc` is at or after `intake_utc` (otherwise
    `ERR_INTAKE_NOT_DUE`)."

    Design: Corner/state_machines/complete_intake_before_due_rejected
    """
    clinic = create_clinic()  # clock at default 2026-05-01
    patient = register_patient(clinic["id"])
    validate_success(
        api.schedule_intake(clinic["id"], patient["id"], {"intake_utc": "2026-06-01T00:00:00Z"}, INTAKE), 200
    )
    resp = api.complete_intake(clinic["id"], patient["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_DUE.value)
    after = validate_success(api.get_patient(clinic["id"], patient["id"], INTAKE), 200)
    assert after["status"] == "INTAKE_SCHEDULED"


def test_activate_patient_without_active_plan_rejected(api):
    """PRD 3.2: "requires that at least one `TreatmentPlan` for the patient has already reached
    `ACTIVE`, `PROCEDURE_PATH`, or `MEDICATION_PATH` (otherwise `ERR_NO_ACTIVE_PLAN`)."

    Design: Corner/state_machines/activate_patient_without_active_plan_rejected
    """
    clinic = create_clinic()
    patient = register_patient(clinic["id"])
    validate_success(
        api.schedule_intake(clinic["id"], patient["id"], {"intake_utc": "2026-05-01T00:00:00Z"}, INTAKE), 200
    )
    validate_success(api.complete_intake(clinic["id"], patient["id"], INTAKE), 200)

    resp = api.activate_patient(clinic["id"], patient["id"], INTAKE)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PLAN.value)
    after = validate_success(api.get_patient(clinic["id"], patient["id"], INTAKE), 200)
    assert after["status"] == "INTAKE_COMPLETE"


def test_route_medication_plan_reaches_medication_path(api):
    """PRD 3.3: "If instead the plan is a medication plan (`requires_medication` is true),
    routing moves it from `ACTIVE` to `MEDICATION_PATH`, and only from that point may
    prescriptions reference the plan."

    Design: Corner/state_machines/route_plan_modality_mismatch_rejected
    """
    clinic = create_clinic()
    prescriber = create_prescriber(clinic["id"])
    patient = register_patient(clinic["id"])
    pres_h = make_prescriber_headers(prescriber["id"])

    plan = validate_success(
        api.create_treatment_plan(clinic["id"], patient["id"], {"modality": "MEDICATION"}, pres_h), 201
    )
    validate_success(api.approve_treatment_plan(clinic["id"], patient["id"], plan["id"], pres_h), 200)
    routed = validate_success(api.route_treatment_plan(clinic["id"], patient["id"], plan["id"], pres_h), 200)
    assert routed["status"] == "MEDICATION_PATH"
    assert routed["requires_medication"] is True


def test_counter_sign_sets_signed_and_expires(api):
    """PRD 3.4: "the system stamps `signed_utc` with the clinic's `current_utc` and sets
    `expires_utc` to `signed_utc` plus the agreement validity window of 365 days."

    Design: Corner/state_machines/agreement_counter_sign_sets_expiry
    """
    clinic = create_clinic(clock_utc="2026-06-01T00:00:00Z")
    prescriber = create_prescriber(clinic["id"])
    patient = register_patient(clinic["id"])
    ag = create_draft_agreement(clinic["id"], patient["id"], prescriber["id"])

    pres_h = make_prescriber_headers(prescriber["id"])
    signed = validate_success(api.counter_sign_agreement(clinic["id"], ag["id"], pres_h), 200)
    assert signed["status"] == "ACTIVE"
    assert signed["signed_utc"].startswith("2026-06-01T00:00:00")
    assert signed["expires_utc"].startswith("2027-06-01T00:00:00")
