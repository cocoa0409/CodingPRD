"""Appointment booking, the parallel clinical x billing dimensions, and state errors.

Covers the parallel state-machine difficulty instance plus appointment corner
instances (initial states, invalid transitions, terminal lockdown, FK existence,
end-before-start, existence-before-state ordering).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_practitioner_headers,
    assert_appointment,
    create_appointment_payload,
    setup_clinic_scenario, book_appointment, check_in_and_complete, get_plan_version,
    BOGUS_UUID,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


# ─── Parallel clinical x billing state machine (queue A) ───────────────────
def test_no_show_drives_parallel_clinical_and_billing_axes(api):
    """PRD 3.5: "Marking an appointment as a no-show requires it to be SCHEDULED
    (otherwise ERR_APPT_NOT_SCHEDULED). It moves the clinical status from SCHEDULED
    to NO_SHOW, records this appointment as the producing strike by increasing the
    patient's strike_count by one and incrementing the patient's version, voids every
    ATTACHED add-on for the appointment (moving each to VOIDED), and increments the
    appointment's version."
    PRD 3.5: "when the penalty is greater than zero a Charge of charge type PENALTY is
    created and the billing status moves to PENALTY_DUE, and when the penalty equals
    zero the billing status moves to WAIVED."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_clinical_x_billing
    """
    ctx = setup_clinic_scenario()  # non-member patient, strike_count 0
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-05T09:00:00Z",
                            scheduled_end="2026-06-05T09:45:00Z")
    result = validate_success(api.no_show(appt["id"], ADMIN), 200)
    assert result["clinical_status"] == "NO_SHOW"
    assert result["billing_status"] == "PENALTY_DUE"


def test_appointment_billing_independent_of_clinical_on_completion(api):
    """PRD 3.5: "Completion moves the clinical status to COMPLETED and, in the
    parallel billing dimension, moves the billing status to BILLED, incrementing the
    appointment's version."

    Design: Difficulty/non_linear_state_machine/appointment_parallel_clinical_x_billing
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=10000,
                            scheduled_start="2026-06-05T12:00:00Z",
                            scheduled_end="2026-06-05T12:45:00Z")
    completed = check_in_and_complete(ctx, appt["id"], clock_iso="2026-06-05T12:00:00Z")
    assert completed["clinical_status"] == "COMPLETED"
    assert completed["billing_status"] == "BILLED"


# ─── Appointment initial state (corner) ────────────────────────────────────
def test_freshly_booked_appointment_initial_states(api):
    """PRD 3.5: "A new appointment opens with its clinical dimension, clinical_status,
    at SCHEDULED and its billing dimension, billing_status, at UNBILLED; these two
    state machines evolve independently of one another."
    PRD 3.5: "The arrival_class begins as PENDING and is resolved at check-in: taking the
    difference in seconds between checked_in_at and scheduled_start, the arrival is
    classified LATE when that difference is strictly greater than the grace allowance of
    ten minutes, and ON_TIME otherwise."

    Design: Corner/state_machines/appointment_initial_states_on_creation
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-20T10:00:00Z",
                            scheduled_end="2026-06-20T10:45:00Z")
    assert_appointment(appt)
    assert appt["clinical_status"] == "SCHEDULED"
    assert appt["billing_status"] == "UNBILLED"
    assert appt["arrival_class"] == "PENDING"
    assert appt["version"] == 1


# ─── Appointment invalid transitions / terminal lockdown (corner) ──────────
def test_complete_scheduled_appointment_rejected_not_checked_in(api):
    """PRD 3.5: "Completion is a Practitioner action requiring the appointment to be
    CHECKED_IN (otherwise ERR_APPT_NOT_CHECKED_IN)."

    Design: Corner/state_machines/complete_scheduled_appointment_rejected_not_checked_in
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-17T10:00:00Z",
                            scheduled_end="2026-06-17T10:45:00Z")
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    validate_error(api.complete_appointment(appt["id"], ph),
                   ApiErrorId.ERR_APPT_NOT_CHECKED_IN.value)


def test_cancel_completed_appointment_terminal_lockdown(api):
    """PRD 3.5: "Cancelling an appointment requires its clinical status to be
    SCHEDULED or CHECKED_IN (otherwise ERR_APPT_NOT_CANCELLABLE) and follows a
    transitive cascade."

    Design: Corner/state_machines/cancel_completed_appointment_terminal_lockdown
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-18T10:00:00Z",
                            scheduled_end="2026-06-18T10:45:00Z")
    check_in_and_complete(ctx, appt["id"], clock_iso="2026-06-18T10:00:00Z")
    validate_error(api.cancel_appointment(appt["id"], ADMIN),
                   ApiErrorId.ERR_APPT_NOT_CANCELLABLE.value)


# ─── FK existence & body validation (corner) ───────────────────────────────
def test_booking_with_nonexistent_room_fk_not_found(api):
    """PRD 2.8: "After path existence, foreign keys supplied in the request body are
    checked for existence (for booking, plan creation, and dispense creation), again
    drawing from the not-found vocabulary just listed (ERR_PRACTITIONER_NOT_FOUND,
    ERR_ROOM_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_PACKAGE_NOT_FOUND, ERR_INTAKE_NOT_FOUND,
    ERR_FORMULA_NOT_FOUND)."

    Design: Corner/entities/appointment_body_fk_room_not_found
    """
    ctx = setup_clinic_scenario()
    plv = get_plan_version(ctx["plan"]["id"])
    payload = create_appointment_payload(
        ctx["patient"]["id"], ctx["plan"]["id"], ctx["practitioner"]["id"],
        "00000000-0000-4000-8000-0000000000bb", plv,
        scheduled_start="2026-06-15T10:00:00Z", scheduled_end="2026-06-15T10:45:00Z")
    validate_error(api.create_appointment(payload, ADMIN),
                   ApiErrorId.ERR_ROOM_NOT_FOUND.value)


def test_booking_end_before_start_rejected(api):
    """PRD 2.8: "Only then is the body checked for well-formedness (ERR_INVALID_REQUEST):
    required fields present, enum values legal, the appointment's scheduled_end strictly
    after its scheduled_start, every numeric field at or above its minimum, and
    coinsurance_rate within the inclusive range from 0 to 1."

    Design: Corner/entities/appointment_end_before_start_rejected
    """
    ctx = setup_clinic_scenario()
    plv = get_plan_version(ctx["plan"]["id"])
    payload = create_appointment_payload(
        ctx["patient"]["id"], ctx["plan"]["id"], ctx["practitioner"]["id"],
        ctx["room"]["id"], plv,
        scheduled_start="2026-06-15T11:00:00Z", scheduled_end="2026-06-15T10:00:00Z")
    validate_error(api.create_appointment(payload, ADMIN),
                   ApiErrorId.ERR_INVALID_REQUEST.value)


def test_check_in_nonexistent_appointment_existence_precedes_state(api):
    """PRD 2.8: "Next, any resource identifiers embedded in the request path are checked
    for existence in left-to-right order, so that on a path naming more than one resource
    the earlier identifier's not-found error is returned before the later one is even
    consulted; depending on the resource this surfaces as ERR_PATIENT_NOT_FOUND,
    ERR_INTAKE_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_PACKAGE_NOT_FOUND, ERR_APPT_NOT_FOUND,
    ERR_DISPENSE_NOT_FOUND, ERR_PRACTITIONER_NOT_FOUND, ERR_ROOM_NOT_FOUND,
    ERR_FORMULA_NOT_FOUND, or ERR_HERB_NOT_FOUND."
    PRD 2.8: "After these foundational checks, state preconditions for the requested
    transition are evaluated (the various ERR_*_NOT_* conflict errors), followed by
    cross-entity referential rules, then the domain-specific safety, temporal, and fiscal
    rules, and finally the optimistic-concurrency version check."

    Design: Corner/validations/existence_precedes_state_on_checkin
    """
    validate_error(api.check_in(BOGUS_UUID, ADMIN), ApiErrorId.ERR_APPT_NOT_FOUND.value)
