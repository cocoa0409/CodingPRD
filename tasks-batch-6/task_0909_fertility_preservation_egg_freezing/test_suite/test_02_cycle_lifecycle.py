"""Stimulation-cycle state machine: scheduling gates, suspend/resume cycle, trigger
boundary, cancellation cascade, and invalid transitions.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_consultation_payload, create_cycle_payload,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------- Difficulty: suspend/resume cycle
def test_cycle_suspend_moves_monitoring_to_suspended(api):
    """PRD §3.3: "Suspension moves a cycle from MONITORING to SUSPENDED; while suspended, the
    cycle is frozen and any attempt to create a new monitoring appointment for it is rejected
    on the state check."

    Design: Difficulty/non_linear_state_machine/cycle_monitoring_suspend_resume_cycle
    """
    b = fx.setup_monitoring_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=31)
    phys = fx.make_physician_headers(b["phys_id"])
    data = validate_success(api.suspend_cycle(b["cycle_id"], phys), 200)
    assert data["status"] == "SUSPENDED", f"suspend must yield SUSPENDED, got {data['status']}"


def test_cycle_resume_returns_suspended_to_monitoring(api):
    """PRD §3.3: "Resumption moves it from SUSPENDED back to MONITORING, and a cycle may cycle
    between these two states any number of times."

    Design: Difficulty/non_linear_state_machine/cycle_monitoring_suspend_resume_cycle
    """
    b = fx.setup_monitoring_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=31)
    phys = fx.make_physician_headers(b["phys_id"])
    validate_success(api.suspend_cycle(b["cycle_id"], phys), 200)
    data = validate_success(api.resume_cycle(b["cycle_id"], phys), 200)
    assert data["status"] == "MONITORING", f"resume must return to MONITORING, got {data['status']}"


# --------------------------------------------------------------- Difficulty: schedule gate
def test_schedule_rejected_when_consultation_not_completed(api):
    """PRD §3.3: "This is permitted only when the referenced consultation is in COMPLETED
    status and its eligibility_status is ELIGIBLE; if the consultation is not both completed
    and eligible, the request is rejected with ERR_CONSULTATION_NOT_ELIGIBLE."

    Design: Difficulty/cross_entity_state_dependency/cycle_schedule_requires_eligible_consult
    """
    patient = fx.create_patient()
    consult = fx.get_success_data(api.create_consultation(
        create_consultation_payload(patient["id"], amh_level=3.0, antral_follicle_count=16), COORD))
    cyc = fx.get_success_data(api.create_stimulation_cycle(
        create_cycle_payload(patient["id"], consult["id"]), COORD))
    resp = api.schedule_cycle(cyc["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CONSULTATION_NOT_ELIGIBLE.value, 422)


def test_schedule_rejected_when_consultation_ineligible(api):
    """PRD §3.3: "This is permitted only when the referenced consultation is in COMPLETED
    status and its eligibility_status is ELIGIBLE; if the consultation is not both completed
    and eligible, the request is rejected with ERR_CONSULTATION_NOT_ELIGIBLE." PRD §3.2: "The
    consultation is marked ELIGIBLE when the amh_level is at least 0.5 ng/mL, and INELIGIBLE
    otherwise."

    Design: Difficulty/cross_entity_state_dependency/cycle_schedule_requires_eligible_consult
    """
    phys_id = fx.create_physician("Dr Inelig")
    patient = fx.create_patient()
    # amh 0.3 < 0.5 => INELIGIBLE after complete.
    consult = fx.complete_eligible_consultation(patient["id"], phys_id, amh_level=0.3,
                                                antral_follicle_count=5, patient_age_years=31)
    assert consult["eligibility_status"] == "INELIGIBLE"
    cyc = fx.get_success_data(api.create_stimulation_cycle(
        create_cycle_payload(patient["id"], consult["id"]), COORD))
    resp = api.schedule_cycle(cyc["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_CONSULTATION_NOT_ELIGIBLE.value, 422)


# --------------------------------------------------------------- Difficulty: trigger min-visits boundary
def test_trigger_rejected_below_min_monitoring_visits(api):
    """PRD §3.4: "Triggering requires that the cycle's monitoring_visit_count be at least 3;
    a cycle with fewer than three non-cancelled monitoring visits is rejected with
    ERR_INSUFFICIENT_MONITORING_VISITS."

    Design: Difficulty/boundary_precision_check/cycle_trigger_min_visits_boundary
    """
    b = fx.setup_scheduled_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=31)
    fx.add_monitoring_appointments(b["cycle_id"], b["phys_id"], fx.DEFAULT_APPT_WINDOWS[:2])
    phys = fx.make_physician_headers(b["phys_id"])
    resp = api.trigger_cycle(b["cycle_id"], phys)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MONITORING_VISITS.value, 422)


def test_trigger_succeeds_at_min_monitoring_visits(api):
    """PRD §3.4: "Triggering requires that the cycle's `monitoring_visit_count` be at least 3;
    a cycle with fewer than three non-cancelled monitoring visits is rejected with
    `ERR_INSUFFICIENT_MONITORING_VISITS`. On success the server records `trigger_at` from the
    logical clock."

    Design: Difficulty/boundary_precision_check/cycle_trigger_min_visits_boundary
    """
    b = fx.setup_triggered_cycle(num_visits=3, amh_level=3.0, antral_follicle_count=16,
                                 patient_age_years=31)
    assert b["triggered_cycle"]["status"] == "TRIGGERED", "exactly 3 visits must permit trigger"


# --------------------------------------------------------------- Corner: invalid transitions & cascade
def test_trigger_from_draft_cycle_invalid_state(api):
    """PRD §2.7: "Any attempt to drive a resource through a transition for which it is not in
    the correct originating state is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/trigger_from_draft_cycle_returns_invalid_state
    """
    phys_id = fx.create_physician("Dr Draft")
    patient = fx.create_patient()
    consult = fx.get_success_data(api.create_consultation(
        create_consultation_payload(patient["id"], amh_level=2.0, antral_follicle_count=12), COORD))
    cyc = fx.get_success_data(api.create_stimulation_cycle(
        create_cycle_payload(patient["id"], consult["id"]), COORD))
    resp = api.trigger_cycle(cyc["id"], fx.make_physician_headers(phys_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_complete_already_completed_consultation_invalid_state(api):
    """PRD §3.2: "Only a Physician may complete a consultation, which is legal only while it
    is in REQUESTED status and drives it to COMPLETED."

    Design: Corner/state_machines/complete_already_completed_consultation_returns_invalid_state
    """
    phys_id = fx.create_physician("Dr Comp")
    patient = fx.create_patient()
    consult = fx.get_success_data(api.create_consultation(
        create_consultation_payload(patient["id"], amh_level=2.0, antral_follicle_count=12), COORD))
    phys = fx.make_physician_headers(phys_id)
    validate_success(api.complete_consultation(consult["id"], phys), 200)
    resp = api.complete_consultation(consult["id"], phys)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_cancel_monitoring_cycle_cancels_scheduled_appointment(api):
    """PRD §3.4: "Cancellation releases the estimated cost with no charge, and cascades to the
    monitoring calendar by setting the visit_status of every one of that cycle's still-SCHEDULED
    monitoring appointments to CANCELLED (appointments already cancelled are untouched)."

    Design: Corner/endpoints/cancel_cycle_cascades_appointment_cancellation
    """
    b = fx.setup_monitoring_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=30)
    appt_id = b["appointments"][0]["id"]
    data = validate_success(api.cancel_cycle(b["cycle_id"], COORD), 200)
    assert data["status"] == "CANCELLED", "cancelled cycle must be CANCELLED"
    appt = validate_success(api.get_monitoring_appointment(appt_id, COORD), 200)
    assert appt["visit_status"] == "CANCELLED", "scheduled appointment must cascade to CANCELLED"
