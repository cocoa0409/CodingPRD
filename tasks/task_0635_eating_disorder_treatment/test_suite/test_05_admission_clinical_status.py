"""Admission clinical-status dimension: the medical-hold cycle (orthogonal to
level of care), the reconciled-risk ratchet, and invalid-state guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    CLINICIAN,
    INTAKE,
    fixtures as fx,
)


def test_hold_then_clear_leaves_status_and_loc_unchanged(api):
    """PRD §3.5: "A `Clinician` clears a hold, moving the status back from
    `MEDICAL_HOLD` to `ADMITTED`".
    PRD §3.8: "The admission's clinical status stays `ADMITTED` throughout —
    step-down only changes the level-of-care dimension."

    Design: Difficulty/non_linear_state_machine/admission_parallel_dimensions_status_and_loc
    """
    ctx = fx.setup_admitted_admission(level_of_care="RESIDENTIAL")
    aid = ctx["admission"]["id"]
    assert ctx["admission"]["level_of_care"] == "RESIDENTIAL"
    validate_success(api.medical_hold_admission(aid, CLINICIAN))
    cleared = validate_success(api.clear_hold_admission(aid, CLINICIAN))
    assert cleared["clinical_status"] == "ADMITTED", (
        f"expected ADMITTED, got {cleared['clinical_status']}"
    )
    assert cleared["level_of_care"] == "RESIDENTIAL", (
        f"level_of_care must be unchanged, got {cleared['level_of_care']}"
    )


def test_medical_hold_moves_admitted_to_medical_hold(api):
    """PRD §3.5: "a `Clinician` may place a **medical hold**, moving the clinical
    status from `ADMITTED` to `MEDICAL_HOLD`; this is legal only from `ADMITTED`,
    else `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/admission_parallel_dimensions_status_and_loc
    """
    ctx = fx.setup_admitted_admission()
    held = validate_success(api.medical_hold_admission(ctx["admission"]["id"], CLINICIAN))
    assert held["clinical_status"] == "MEDICAL_HOLD", (
        f"expected MEDICAL_HOLD, got {held['clinical_status']}"
    )


def test_medical_hold_bumps_reconciled_risk_and_posture(api):
    """PRD §3.5: "Placing a hold adds 10 to the patient's running
    `nutritional_risk_score` (the reconciled variant) and recomputes the
    `medical_stability_posture` from the new score."

    Design: Corner/calculations/medical_hold_bumps_reconciled_risk_and_posture
    """
    # provisional 44 (STABLE); one hold -> 54 (GUARDED, >=50).
    ctx = fx.setup_admitted_admission()
    pid = ctx["patient"]["id"]
    before = validate_success(api.get_patient(pid, INTAKE))
    assert before["nutritional_risk_score"] == 44.0, (
        f"precondition: expected 44.0, got {before['nutritional_risk_score']}"
    )
    validate_success(api.medical_hold_admission(ctx["admission"]["id"], CLINICIAN))
    after = validate_success(api.get_patient(pid, INTAKE))
    assert after["nutritional_risk_score"] == 54.0, (
        f"expected 54.0, got {after['nutritional_risk_score']}"
    )
    assert after["medical_stability_posture"] == "GUARDED", (
        f"expected GUARDED, got {after['medical_stability_posture']}"
    )


def test_medical_hold_from_waitlisted_invalid_state(api):
    """PRD §3.5: "a `Clinician` may place a **medical hold**, moving the clinical
    status from `ADMITTED` to `MEDICAL_HOLD`; this is legal only from `ADMITTED`,
    else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/medical_hold_from_waitlisted_returns_invalid_state
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    admission = fx.create_admission(
        patient["id"], facility["id"], program["id"], cohort["id"]
    )
    resp = api.medical_hold_admission(admission["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_admission_initial_state_is_waitlisted(api):
    """PRD §3.4: "A new admission starts `WAITLISTED` on its clinical dimension."

    Design: Corner/state_machines/admission_initial_state_is_waitlisted
    """
    facility, program, cohort = fx.create_substrate()
    patient = fx.create_patient(facility["id"])
    resp = api.create_admission(
        {
            "patient_id": patient["id"],
            "facility_id": facility["id"],
            "program_id": program["id"],
            "cohort_id": cohort["id"],
            "requested_length_of_stay_days": 7,
        },
        INTAKE,
    )
    data = validate_success(resp, expected_status=201)
    assert data["clinical_status"] == "WAITLISTED", (
        f"expected WAITLISTED, got {data['clinical_status']}"
    )


def test_discharged_admission_rejects_second_begin_discharge(api):
    """PRD §3.9: "A `Clinician` first begins discharge, moving an `ADMITTED`
    admission to `DISCHARGE_PENDING` (legal only from `ADMITTED`, else
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/discharge_terminal_admission_rejects_second_begin_discharge
    """
    ctx = fx.setup_discharge_pending(with_meal_plan=False)
    aid = ctx["admission"]["id"]
    validate_success(api.discharge_admission(aid, CLINICIAN))
    data = validate_success(api.get_admission(aid, CLINICIAN))
    assert data["clinical_status"] == "DISCHARGED"
    resp = api.begin_discharge_admission(aid, CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
