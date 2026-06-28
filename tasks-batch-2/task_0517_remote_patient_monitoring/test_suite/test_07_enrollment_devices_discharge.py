"""Patient enrollment dimensions, device lifecycle, and the discharge cascade.

Covers difficulty rules transitive_cascade (discharge depth-3) and
cross_entity_state_dependency (device activate requires enrolled patient), plus
corner claims for suspension cross-dimension cascade, invalid device transitions,
and the enrollment gate on enroll / vitals.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_vitals_payload, TEST_USERS, ApiErrorId, set_clock,
    setup_enrolled_patient, setup_enrolled_patient_with_active_device,
    create_payer, create_patient, create_consent, create_care_plan,
    activate_care_plan, create_device, activate_device,
)

CC = TEST_USERS["care_coordinator_headers"]
CLIN = TEST_USERS["clinician_headers"]


def test_discharge_cascades_device_return_then_monitoring_off(api):
    """PRD §3.3: "A successful discharge sets `enrollment_status` to `DISCHARGED`, forces
    `monitoring_status` to `INACTIVE`, and cascades over the patient's hardware: every
    device whose `status` is `ENROLLED` or `ACTIVE` is moved to `RETURNED`, and the
    active care plan is retired as described in §3.2."

    Design: Difficulty/transitive_cascade/discharge_cascade_depth3_device_return_then_monitoring_off
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-DC-1", serial_number="SN-DC-1", consent_type="RPM")
    pid = ctx["patient"]["id"]
    discharged = validate_success(api.discharge_patient(pid, CC), 200)
    assert discharged["enrollment_status"] == "DISCHARGED"
    assert discharged["monitoring_status"] == "INACTIVE"
    device = get_success_data(api.get_device(ctx["device"]["id"], CC))
    assert device["status"] == "RETURNED", "ACTIVE device cascades to RETURNED"


def test_discharge_retires_active_care_plan_and_clears_pointer(api):
    """PRD §3.2: "When a patient is discharged, any `ACTIVE` care plan is retired
    automatically: it transitions `ACTIVE → RETIRED`, the patient's `care_plan_id` is
    cleared to null, and the plan's version increments."

    Design: Difficulty/transitive_cascade/discharge_cascade_depth3_device_return_then_monitoring_off
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-DC-2", serial_number="SN-DC-2", consent_type="RPM")
    pid = ctx["patient"]["id"]
    discharged = validate_success(api.discharge_patient(pid, CC), 200)
    assert discharged["care_plan_id"] is None, "care_plan_id cleared on discharge"
    plan = get_success_data(api.get_care_plan(ctx["plan"]["id"], CC))
    assert plan["status"] == "RETIRED", "active care plan retired on discharge"


def test_activate_device_requires_patient_enrolled(api):
    """PRD §3.4: "Activating a device requires that the device be `ENROLLED` and that the
    patient's `enrollment_status` be `ENROLLED`."
    PRD §2.5: "State-transition legality (`ERR_INVALID_STATE`) is evaluated ... when the
    target entity is not in a state from which the requested transition is defined."

    Design: Difficulty/cross_entity_state_dependency/device_activate_requires_patient_enrolled
    """
    payer = create_payer(name="P-CE1")
    patient = create_patient(payer["id"], mrn="M-CE1-1")  # PENDING_CONSENT
    device = create_device(patient["id"], serial_number="SN-CE1-1")
    resp = api.activate_device(patient["id"], device["id"], CC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_device_on_pending_patient_leaves_device_enrolled(api):
    """PRD §3.4: "Activating a device requires that the device be `ENROLLED` and that the
    patient's `enrollment_status` be `ENROLLED`."
    PRD §3.4: "A newly enrolled device begins with `status` of `ENROLLED`, a null
    `activated_at`, and `setup_billed` false."

    Design: Difficulty/cross_entity_state_dependency/device_activate_requires_patient_enrolled
    """
    payer = create_payer(name="P-CE1b")
    patient = create_patient(payer["id"], mrn="M-CE1-2")
    device = create_device(patient["id"], serial_number="SN-CE1-2")
    api.activate_device(patient["id"], device["id"], CC)
    after = get_success_data(api.get_device(device["id"], CC))
    assert after["status"] == "ENROLLED", "rejected activation leaves device ENROLLED"


def test_suspend_pauses_monitoring_cross_dimension(api):
    """PRD §3.3: "Suspension applies only to an enrolled patient. It moves
    `enrollment_status` from `ENROLLED` to `SUSPENDED`. If the patient was actively
    monitoring at the time, the suspension cascades across dimensions and moves
    `monitoring_status` from `MONITORING` to `PAUSED`."

    Design: Corner/state_machines/suspend_pauses_monitoring_cross_dimension
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-SM7-1", serial_number="SN-SM7-1", consent_type="RPM")
    suspended = validate_success(api.suspend_patient(ctx["patient"]["id"], CC), 200)
    assert suspended["enrollment_status"] == "SUSPENDED"
    assert suspended["monitoring_status"] == "PAUSED"


def test_activate_returned_device_is_invalid_state(api):
    """PRD §3.4: "`RETURNED` is terminal for a device."
    PRD §2.5: "State-transition legality (`ERR_INVALID_STATE`) is evaluated ... when the
    target entity is not in a state from which the requested transition is defined."

    Design: Corner/state_machines/device_activate_invalid_from_returned_returns_invalid_state
    """
    ctx = setup_enrolled_patient(mrn="M-SM1-1", consent_type="RPM")
    pid = ctx["patient"]["id"]
    device = create_device(pid, serial_number="SN-SM1-1")
    activate_device(pid, device["id"])
    validate_success(api.return_device(pid, device["id"], CC), 200)
    resp = api.activate_device(pid, device["id"], CC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_vitals_for_non_enrolled_patient_rejected(api):
    """PRD §3.3: "transmitting vitals or logging a care activity requires the patient's
    `enrollment_status` to be `ENROLLED`, and an attempt while not enrolled is refused
    with `ERR_CONSENT_REQUIRED` — the same code used for the enroll-readiness failure."

    Design: Corner/validations/vitals_requires_enrolled_patient
    """
    payer = create_payer(name="P-V1")
    patient = create_patient(payer["id"], mrn="M-V1-1")  # PENDING_CONSENT
    device = create_device(patient["id"], serial_number="SN-V1-1")
    resp = api.create_vitals(
        patient["id"],
        create_vitals_payload(device["id"], 120, "2026-05-02T08:00:00Z"), CLIN)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value)


def test_enroll_without_active_consent_rejected(api):
    """PRD §3.3: "Enrollment readiness demands two things together: an `ACTIVE` consent
    record covering either `RPM` or `BOTH`, and an `ACTIVE` care plan for the patient. If
    either is missing the enroll is refused with `ERR_CONSENT_REQUIRED`."

    Design: Corner/validations/enroll_without_active_consent_rejected
    """
    payer = create_payer(name="P-V2")
    patient = create_patient(payer["id"], mrn="M-V2-1")
    plan = create_care_plan(patient["id"])
    activate_care_plan(patient["id"], plan["id"])  # ACTIVE plan but no consent
    resp = api.enroll_patient(patient["id"], CC)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value)
    after = get_success_data(api.get_patient(patient["id"], CC))
    assert after["enrollment_status"] == "PENDING_CONSENT", "enroll did not advance"
