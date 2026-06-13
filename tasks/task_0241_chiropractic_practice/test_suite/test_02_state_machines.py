"""Appointment parallel dimensions, the cyclic plan-phase regression, phase
bubble-up, SOAP signing/lockdown, and invalid-state guards.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_provider_headers,
    create_appointment_payload,
    create_soap_note_payload,
    setup_base_practice,
    create_cash_patient,
    create_insurance_patient,
    add_policy,
    create_attended_appointment,
    create_checked_in_with_signed_soap,
    create_finalized_exam,
    propose_plan,
    add_phase,
    activate_plan,
    setup_active_plan,
    setup_plan_with_corrective_in_progress,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
BILLING = TEST_USERS["billing_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty: non_linear_state_machine / appointment_parallel_attendance_x_billing
# ===========================================================================
def test_adjudicate_advances_billing_without_touching_attendance(api):
    """PRD §3.8: "The attendance dimension is untouched, so an `ATTENDED`/`POSTED`
    appointment becomes `ATTENDED`/`ADJUDICATED`."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_attendance_x_billing
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Ins Ida")
    policy = add_policy(
        patient["id"], annual_visit_cap=20, deductible_total_cents=0,
        coinsurance_pct=0.20, allowed_amount_cents=8000,
    )
    appt = create_attended_appointment(
        patient["id"], base["provider"]["id"], base["room"]["id"],
        scheduled_start="2026-03-03T17:00:00Z", insurance_policy_id=policy["id"],
    )
    assert appt["attendance_status"] == "ATTENDED"
    assert appt["billing_status"] == "POSTED"

    res = validate_success(api.adjudicate_appointment(patient["id"], appt["id"], BILLING), 200)
    assert res["attendance_status"] == "ATTENDED"
    assert res["billing_status"] == "ADJUDICATED"


def test_attended_posted_visit_has_independent_dimensions(api):
    """PRD §3.7: "On completion the appointment transitions `CHECKED_IN →
    ATTENDED`."
    PRD §3.7: "moves `billing_status` `UNBILLED → POSTED`".

    Completion advances attendance to ATTENDED and billing to POSTED — two
    independent dimensions evolving on the same appointment.

    Design: Difficulty/non_linear_state_machine/appointment_parallel_attendance_x_billing
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Ins Ivan")
    policy = add_policy(
        patient["id"], annual_visit_cap=20, deductible_total_cents=0,
        coinsurance_pct=0.20, allowed_amount_cents=8000,
    )
    appt = create_attended_appointment(
        patient["id"], base["provider"]["id"], base["room"]["id"],
        scheduled_start="2026-03-03T17:00:00Z", insurance_policy_id=policy["id"],
    )
    assert appt["attendance_status"] == "ATTENDED"
    assert appt["billing_status"] == "POSTED"
    assert appt["patient_responsibility_cents"] == 1600  # round(8000*0.20), deductible 0


# ===========================================================================
# Difficulty: non_linear_state_machine / plan_phase_cyclic_corrective_back_to_acute
# ===========================================================================
def test_regression_returns_current_phase_to_acute(api):
    """PRD §3.4: "On a valid regression the corrective phase transitions
    `IN_PROGRESS → PENDING`, and the lowest-`sequence_index` `ACUTE` phase that
    had already `COMPLETED` is moved back to `IN_PROGRESS` with its
    `visits_completed` reset to 0; the plan's `current_phase` returns to `ACUTE`."

    Design: Difficulty/non_linear_state_machine/plan_phase_cyclic_corrective_back_to_acute
    """
    ctx = setup_plan_with_corrective_in_progress(reexam_severity=8)
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    res = validate_success(
        api.re_exam_regress(
            pid,
            ctx["plan"]["id"],
            {"exam_record_id": ctx["reexam"]["id"], "plan_phase_id": ctx["corrective_phase"]["id"]},
            make_provider_headers(prov_id),
        ),
        200,
    )
    assert res["current_phase"] == "ACUTE"


def test_regression_cycles_phase_states(api):
    """PRD §3.4: "the corrective phase transitions `IN_PROGRESS → PENDING`, and
    the lowest-`sequence_index` `ACUTE` phase that had already `COMPLETED` is
    moved back to `IN_PROGRESS` with its `visits_completed` reset to 0".

    Design: Difficulty/non_linear_state_machine/plan_phase_cyclic_corrective_back_to_acute
    """
    ctx = setup_plan_with_corrective_in_progress(reexam_severity=8)
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    validate_success(
        api.re_exam_regress(
            pid,
            ctx["plan"]["id"],
            {"exam_record_id": ctx["reexam"]["id"], "plan_phase_id": ctx["corrective_phase"]["id"]},
            make_provider_headers(prov_id),
        ),
        200,
    )
    corr = validate_success(api.get_phase_by_id(ctx["corrective_phase"]["id"], make_provider_headers(prov_id)), 200)
    acute = validate_success(api.get_phase_by_id(ctx["acute_phase"]["id"], make_provider_headers(prov_id)), 200)
    assert corr["status"] == "PENDING"
    assert acute["status"] == "IN_PROGRESS"
    assert acute["visits_completed"] == 0


# ===========================================================================
# Corner: state_machines / phase_bubble_up_completes_plan
# ===========================================================================
def test_phase_completion_bubbles_up_to_complete_plan(api):
    """PRD §3.4: "If instead the completed phase was the highest-`sequence_index`
    phase and it was a `MAINTENANCE` phase, the completion bubbles up to move the
    plan `ACTIVE → COMPLETED`."

    Design: Corner/state_machines/phase_bubble_up_completes_plan
    """
    ctx = setup_active_plan(
        payer_mode="CASH",
        phases=[{"phase_type": "MAINTENANCE", "sequence_index": 0, "visits_per_week": 1, "planned_visit_count": 1}],
    )
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    phase = ctx["phases"][0]
    create_attended_appointment(
        pid, prov_id, ctx["room"]["id"], scheduled_start="2026-03-03T17:00:00Z", plan_phase_id=phase["id"]
    )
    plan = validate_success(api.get_plan_by_id(ctx["plan"]["id"], make_provider_headers(prov_id)), 200)
    phase_after = validate_success(api.get_phase_by_id(phase["id"], make_provider_headers(prov_id)), 200)
    assert phase_after["status"] == "COMPLETED"
    assert plan["status"] == "COMPLETED"
    assert plan["visits_delivered"] == 1


# ===========================================================================
# Corner: state_machines / sign_soap_locks_immutable_resign_invalid
# ===========================================================================
def test_sign_soap_locks_and_resign_rejected(api):
    """PRD §3.7: "Signing transitions the note `DRAFT → SIGNED`, after which it is
    immutable".
    PRD §3.7: "signing it requires the note be `DRAFT`".

    Re-signing a SIGNED note targets a transition not defined from SIGNED.

    Design: Corner/state_machines/sign_soap_locks_immutable_resign_invalid
    """
    base = setup_base_practice()
    patient = create_cash_patient("Sign Sid")
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    appt = validate_success(
        api.book_appointment(
            pid, create_appointment_payload(prov_id, base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"),
            FRONTDESK,
        ),
        201,
    )
    validate_success(api.check_in(pid, appt["id"], FRONTDESK), 200)
    validate_success(
        api.create_soap_note(pid, appt["id"], create_soap_note_payload(prov_id), make_provider_headers(prov_id)), 201
    )
    signed = validate_success(api.sign_soap_note(pid, appt["id"], make_provider_headers(prov_id)), 200)
    assert signed["status"] == "SIGNED"

    res = api.sign_soap_note(pid, appt["id"], make_provider_headers(prov_id))
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Corner: state_machines / complete_from_booked_invalid_state
# ===========================================================================
def test_complete_from_booked_is_invalid_state(api):
    """PRD §3.7: "Completing an appointment requires it be `CHECKED_IN` and that
    a `SIGNED` SOAP note exist for it".
    PRD §3.7: "A request that targets a transition the appointment's current state
    does not allow is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_from_booked_invalid_state
    """
    base = setup_base_practice()
    patient = create_cash_patient("State Stan")
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    appt = validate_success(
        api.book_appointment(
            pid, create_appointment_payload(prov_id, base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"),
            FRONTDESK,
        ),
        201,
    )
    res = api.complete_appointment(pid, appt["id"], make_provider_headers(prov_id))
    validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# Corner: state_machines / cancel_already_cancelled_invalid_state
# ===========================================================================
def test_cancel_already_cancelled_is_invalid_state(api):
    """PRD §3.7: "A request that targets a transition the appointment's current
    state does not allow is rejected with `ERR_INVALID_STATE`."

    A second cancel on a CANCELLED appointment targets a transition not defined
    from CANCELLED.

    Design: Corner/state_machines/cancel_already_cancelled_invalid_state
    """
    base = setup_base_practice()
    patient = create_cash_patient("Idem Ida")
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    appt = validate_success(
        api.book_appointment(
            pid, create_appointment_payload(prov_id, base["room"]["id"], scheduled_start="2026-03-20T17:00:00Z"),
            FRONTDESK,
        ),
        201,
    )
    validate_success(api.cancel_appointment(pid, appt["id"], FRONTDESK), 200)
    res = api.cancel_appointment(pid, appt["id"], FRONTDESK)
    validate_error(res, "ERR_INVALID_STATE")
    final = validate_success(api.get_appointment(pid, appt["id"], FRONTDESK), 200)
    assert final["attendance_status"] == "CANCELLED"


# ===========================================================================
# Corner: state_machines / finalize_already_finalized_exam_invalid_state
# ===========================================================================
def test_finalize_already_finalized_exam_is_invalid_state(api):
    """PRD §3.3: "finalization requires the exam still be `DRAFT` and that its
    `provider_id` equal the acting provider's `X-User-ID`".
    PRD §3.7: "A request that targets a transition the appointment's current state
    does not allow is rejected with `ERR_INVALID_STATE`."

    Finalizing an already-FINALIZED (terminal) exam violates the still-`DRAFT`
    precondition; reaching a transition the current state does not allow surfaces
    as `ERR_INVALID_STATE`.

    Design: Corner/state_machines/finalize_already_finalized_exam_invalid_state
    """
    base = setup_base_practice()
    patient = create_cash_patient("Exam Eve")
    pid = patient["id"]
    prov_id = base["provider"]["id"]
    exam = create_finalized_exam(pid, prov_id, severity_score=5)
    res = api.finalize_exam(pid, exam["id"], make_provider_headers(prov_id))
    validate_error(res, "ERR_INVALID_STATE")
