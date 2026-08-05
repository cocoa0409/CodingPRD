"""Monitoring appointment scheduling: buffered provider-overlap rule, state-vs-temporal
precedence, and schema validation of the appointment window.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_consultation_payload, create_cycle_payload,
    create_monitoring_appointment_payload,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------- Difficulty: buffered overlap
def test_appointment_within_provider_buffer_rejected(api):
    """PRD §3.3: "a new monitoring appointment is rejected with ERR_PROVIDER_UNAVAILABLE when
    it overlaps any existing non-cancelled appointment for the same provider once each existing
    appointment is padded by 15 minutes on each side. In other words, the new appointment must
    not fall within 15 minutes of another of that provider's appointments."

    Design: Difficulty/resource_temporal_overlap/provider_appointment_buffered_overlap
    """
    b = fx.setup_monitoring_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=31)
    # Existing appt 09:00-09:30; new 09:40-10:00 leaves only a 10-minute gap (< 15).
    resp = api.create_monitoring_appointment(
        create_monitoring_appointment_payload(
            b["cycle_id"], b["phys_id"], "2026-05-02T09:40:00Z", "2026-05-02T10:00:00Z"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_UNAVAILABLE.value, 409)


def test_appointment_outside_provider_buffer_accepted(api):
    """PRD §3.3: "a new monitoring appointment is rejected with ERR_PROVIDER_UNAVAILABLE when
    it overlaps any existing non-cancelled appointment for the same provider once each existing
    appointment is padded by 15 minutes on each side." A 30-minute gap is outside the buffer.

    Design: Difficulty/resource_temporal_overlap/provider_appointment_buffered_overlap
    """
    b = fx.setup_monitoring_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=31)
    # Existing appt 09:00-09:30; new 10:00-10:30 sits a clear 30 minutes away.
    resp = api.create_monitoring_appointment(
        create_monitoring_appointment_payload(
            b["cycle_id"], b["phys_id"], "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z"),
        COORD)
    data = validate_success(resp, 201)
    assert data["visit_status"] == "SCHEDULED", "non-conflicting appointment must be created"


# --------------------------------------------------------------- Difficulty: state beats temporal
def test_appointment_on_suspended_cycle_returns_invalid_state_over_conflict(api):
    """PRD §2.9: "the target resource being in a legal state for the requested transition
    (ERR_INVALID_STATE); ... and then the business rules of priorities 7 through 18 ... A lower
    priority number always wins." PRD §3.3: "while suspended, the cycle is frozen and any
    attempt to create a new monitoring appointment for it is rejected on the state check."

    Design: Difficulty/priority_pair_validation_conflict/appt_state_beats_provider_temporal
    """
    b = fx.setup_monitoring_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=31)
    phys = fx.make_physician_headers(b["phys_id"])
    validate_success(api.suspend_cycle(b["cycle_id"], phys), 200)
    # New appt exactly overlaps the existing 09:00-09:30 provider booking, but the cycle is
    # SUSPENDED: the state check (priority 5) pre-empts the temporal check (priority 13).
    resp = api.create_monitoring_appointment(
        create_monitoring_appointment_payload(
            b["cycle_id"], b["phys_id"], "2026-05-02T09:00:00Z", "2026-05-02T09:30:00Z"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_appointment_on_suspended_cycle_without_conflict_still_invalid_state(api):
    """PRD §2.9: "A lower priority number always wins." PRD §3.3: "while suspended, the cycle
    is frozen and any attempt to create a new monitoring appointment for it is rejected on the
    state check."

    Design: Difficulty/priority_pair_validation_conflict/appt_state_beats_provider_temporal
    """
    b = fx.setup_monitoring_cycle(amh_level=3.0, antral_follicle_count=16, patient_age_years=31)
    phys = fx.make_physician_headers(b["phys_id"])
    validate_success(api.suspend_cycle(b["cycle_id"], phys), 200)
    # A time with no provider conflict at all still fails on the state check.
    resp = api.create_monitoring_appointment(
        create_monitoring_appointment_payload(
            b["cycle_id"], b["phys_id"], "2026-05-02T15:00:00Z", "2026-05-02T15:30:00Z"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# --------------------------------------------------------------- Corner: window schema validation
def test_appointment_end_not_after_start_rejected(api):
    """PRD §2.9: "request-body schema validation such as missing required fields, unknown enum
    values, wrong types, values that violate a non-negative or positive constraint, or a
    `scheduled_end` that is not strictly after `scheduled_start` (`ERR_VALIDATION`)."

    Design: Corner/validations/appointment_end_not_after_start_returns_invalid_request
    """
    phys_id = fx.create_physician("Dr Win")
    patient = fx.create_patient()
    consult = fx.get_success_data(api.create_consultation(
        create_consultation_payload(patient["id"], amh_level=2.0, antral_follicle_count=12), COORD))
    cyc = fx.get_success_data(api.create_stimulation_cycle(
        create_cycle_payload(patient["id"], consult["id"]), COORD))
    resp = api.create_monitoring_appointment(
        create_monitoring_appointment_payload(
            cyc["id"], phys_id, "2026-05-02T10:00:00Z", "2026-05-02T09:00:00Z"),
        COORD)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)
