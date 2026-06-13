"""Corner tests: appointment/deferral state machine, screening calculation boundaries,
collection preconditions, and booking constraints.

Queue B sections: state_machines, calculations, errors.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    create_health_screening_payload, create_donation_payload,
    advance_clock_payload, create_deferral_payload,
    create_center, create_donor, create_slot, book_appointment,
    setup_checked_in_appointment, setup_scheduled_appointment,
    raise_deferral,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
NURSE = TEST_USERS["intake_nurse_headers"]


# ─── state_machines / checkin_already_checked_in ──────────────────────────────
def test_checkin_twice_second_call_returns_not_scheduled(api):
    """PRD §3.4: "The appointment must be SCHEDULED, else ERR_APPOINTMENT_NOT_SCHEDULED."

    Checking the same appointment in twice: the second call hits a CHECKED_IN appointment
    and is rejected with ERR_APPOINTMENT_NOT_SCHEDULED (409).

    Design: Corner/state_machines/checkin_already_checked_in_returns_not_scheduled
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE")
    res = api.check_in_appointment(appt["id"], NURSE)
    validate_error(res, "ERR_APPOINTMENT_NOT_SCHEDULED", expected_status=409)


# ─── state_machines / lift_already_lifted_deferral ────────────────────────────
def test_lift_already_lifted_deferral_returns_not_active(api):
    """PRD §3.2: "An IntakeNurse may lift an active deferral, transitioning it from ACTIVE
    to LIFTED. Lifting requires the deferral to be ACTIVE, otherwise ERR_DEFERRAL_NOT_ACTIVE
    is returned."

    Lifting a LIFTED deferral a second time -> ERR_DEFERRAL_NOT_ACTIVE (409).

    Design: Corner/state_machines/lift_already_lifted_deferral_returns_not_active
    """
    center = create_center(clock=None)
    donor = create_donor(center["id"], full_name="Lift Twice")
    deferral = raise_deferral(donor["id"], category="TRAVEL", kind="TEMPORARY",
                             reason="short trip", duration_days=21)
    get_success_data(api.lift_deferral(deferral["id"], NURSE))
    res = api.lift_deferral(deferral["id"], NURSE)
    validate_error(res, "ERR_DEFERRAL_NOT_ACTIVE", expected_status=409)


# ─── state_machines / no_show_before_slot_window_ends ─────────────────────────
def test_no_show_before_slot_window_ends_returns_slot_window_open(api):
    """PRD §3.6: "Marking a checked-in donor as a no-show is an IntakeNurse action available
    only after the slot window has ended — that is, the center's current_utc must be at or
    after the slot's ends_at, else ERR_SLOT_WINDOW_OPEN."

    With current_utc 09:00 < slot ends_at 18:00, a no-show is rejected.

    Design: Corner/state_machines/no_show_before_slot_window_ends_returns_slot_window_open
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T09:00:00.000Z", donation_type="WHOLE",
        slot_overrides={"starts_at": "2025-01-01T08:00:00.000Z", "ends_at": "2025-01-01T18:00:00.000Z"})
    res = api.no_show_appointment(appt["id"], NURSE)
    validate_error(res, "ERR_SLOT_WINDOW_OPEN", expected_status=409)


# ─── state_machines / temporary_deferral_auto_expires_on_clock_advance ────────
def test_temporary_deferral_auto_expires_on_clock_advance(api):
    """PRD §3.1: "The first sweep examines every ACTIVE deferral that is TEMPORARY: any
    whose expires_at is at or before the new current_utc transitions from ACTIVE to EXPIRED,
    and the affected donor's eligibility_status is recomputed."

    A 14-day TEMPORARY deferral created at 2025-01-01 auto-EXPIRES when the clock advances
    to 2025-01-15, and the donor returns to ELIGIBLE.

    Design: Corner/state_machines/temporary_deferral_auto_expires_on_clock_advance
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], full_name="Temp Expire")
    deferral = raise_deferral(donor["id"], category="MEDICATION", kind="TEMPORARY",
                             reason="antibiotic course", duration_days=14)
    get_success_data(api.advance_clock(center["id"], advance_clock_payload("2025-01-15T00:00:00.000Z"), ADMIN))

    def_after = validate_success(api.get_deferral(deferral["id"], NURSE), 200)
    assert def_after["status"] == "EXPIRED", "current_utc 2025-01-15 >= expires_at -> EXPIRED"
    donor_after = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert donor_after["eligibility_status"] == "ELIGIBLE", "no active deferral left -> ELIGIBLE"


# ─── calculations / hemoglobin_at_exact_floor_passes_screening ────────────────
def test_hemoglobin_at_exact_floor_passes_screening(api):
    """PRD §3.4: "First, hemoglobin: it passes only when hemoglobin_g_dl is at least 12.5
    g/dL (compared at one decimal place, so exactly 12.5 passes); below that, the reason is
    HEMOGLOBIN_LOW."

    A hemoglobin of exactly 12.5 with otherwise-passing measures yields PASS.

    Design: Corner/calculations/hemoglobin_at_exact_floor_passes_screening
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE")
    res = api.create_health_screening(
        create_health_screening_payload(appt["id"], hemoglobin_g_dl=12.5, systolic_bp=120,
                                       pulse_bpm=70, weight_kg=70, recent_travel_risk=False,
                                       disqualifying_medication=False), NURSE)
    screening = validate_success(res, 201)
    assert screening["outcome"] == "PASS", "12.5 == floor satisfies >="


# ─── calculations / screening_travel_risk_auto_raises_temporary_deferral ──────
def test_screening_travel_risk_fails_and_auto_raises_travel_deferral(api):
    """PRD §3.4: "A failing screening has a conditional side effect: when the failure_reason
    is one of HEMOGLOBIN_LOW, TRAVEL_RISK, or MEDICATION, the system automatically raises a
    TEMPORARY deferral against the donor and recomputes their eligibility_status to
    TEMP_DEFERRED. The category and duration follow the reason: ... a TRAVEL_RISK failure
    raises a TRAVEL deferral lasting 21 days ..."

    A screening flagging recent_travel_risk fails with TRAVEL_RISK and auto-raises a
    TEMPORARY TRAVEL deferral, leaving the donor TEMP_DEFERRED.

    Design: Corner/calculations/screening_travel_risk_auto_raises_temporary_deferral
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"blood_type": "A_POS"})
    res = api.create_health_screening(
        create_health_screening_payload(appt["id"], hemoglobin_g_dl=14.0, systolic_bp=120,
                                       pulse_bpm=70, weight_kg=70, recent_travel_risk=True,
                                       disqualifying_medication=False), NURSE)
    screening = validate_success(res, 201)
    assert screening["outcome"] == "FAIL"
    assert screening["failure_reason"] == "TRAVEL_RISK"

    deferrals = validate_success(api.list_deferrals(NURSE, params={"donor_id": donor["id"]}), 200)
    assert any(d["category"] == "TRAVEL" and d["kind"] == "TEMPORARY" for d in deferrals), (
        "TRAVEL_RISK failure auto-raises a TEMPORARY TRAVEL deferral")
    donor_after = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert donor_after["eligibility_status"] == "TEMP_DEFERRED"


# ─── calculations / plasma_per_collection_cap_at_band_boundary_passes ─────────
def test_plasma_per_collection_cap_at_band_boundary_passes(api):
    """PRD §3.5: "a weight of at least 50 kg and below 68 kg caps the collection at 690 mL ...
    The collection's volume_ml must not exceed the applicable band cap, otherwise
    ERR_PLASMA_VOLUME_EXCEEDED (HTTP 422) is returned."

    A 60 kg donor (band cap 690) donating exactly 690 mL plasma passes the per-collection
    cap, creating a COLLECTED donation.

    Design: Corner/calculations/plasma_per_collection_cap_at_band_boundary_passes
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="PLASMA",
        donor_overrides={"weight_kg": 60, "blood_type": "O_POS"})
    get_success_data(api.create_health_screening(
        create_health_screening_payload(appt["id"], hemoglobin_g_dl=13.5, weight_kg=60), NURSE))

    res = api.create_donation(appt["id"], create_donation_payload(volume_ml=690), NURSE)
    donation = validate_success(res, 201)
    assert donation["status"] == "COLLECTED", "690 == band cap 690, <= passes"
    assert donation["volume_ml"] == 690


# ─── errors / donor_second_open_appointment ───────────────────────────────────
def test_second_open_appointment_returns_has_open_appointment(api):
    """PRD §3.3: "And the donor may hold at most one open appointment — that is, at most one
    appointment in SCHEDULED or CHECKED_IN status — at a time; a second concurrent open
    appointment is rejected with ERR_DONOR_HAS_OPEN_APPOINTMENT."

    Design: Corner/errors/donor_second_open_appointment_returns_has_open_appointment
    """
    center = create_center(clock="2025-01-01T00:00:00.000Z")
    donor = create_donor(center["id"], full_name="Two Appts")
    slot1 = create_slot(center["id"], donation_type="WHOLE",
                        starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T18:00:00.000Z", capacity=5)
    slot2 = create_slot(center["id"], donation_type="WHOLE",
                        starts_at="2025-01-03T08:00:00.000Z", ends_at="2025-01-03T18:00:00.000Z", capacity=5)
    book_appointment(donor["id"], slot1)
    res = api.create_appointment(
        {"donor_id": donor["id"], "slot_id": slot2["id"], "expected_slot_version": slot2["version"]}, NURSE)
    validate_error(res, "ERR_DONOR_HAS_OPEN_APPOINTMENT", expected_status=409)


# ─── errors / collect_without_passing_screening ───────────────────────────────
def test_collect_without_passing_screening_returns_screening_not_passed(api):
    """PRD §3.6: "a health screening with outcome of PASS must exist for the appointment,
    else ERR_SCREENING_NOT_PASSED ..."
    PRD §3.4: "The other two failure reasons — UNDERWEIGHT and VITALS_OUT_OF_RANGE — fail
    the screening but do not auto-defer the donor."

    A CHECKED_IN appointment whose only screening FAILED (underweight, no auto-deferral)
    cannot record a collection -> ERR_SCREENING_NOT_PASSED.

    Design: Corner/errors/collect_without_passing_screening_returns_screening_not_passed
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"weight_kg": 48})
    screening = get_success_data(api.create_health_screening(
        create_health_screening_payload(appt["id"], hemoglobin_g_dl=14.0, systolic_bp=120,
                                       pulse_bpm=70, weight_kg=48, recent_travel_risk=False,
                                       disqualifying_medication=False), NURSE))
    assert screening["outcome"] == "FAIL" and screening["failure_reason"] == "UNDERWEIGHT"

    res = api.create_donation(appt["id"], create_donation_payload(volume_ml=450), NURSE)
    validate_error(res, "ERR_SCREENING_NOT_PASSED", expected_status=409)


# ─── errors / book_appointment_nonexistent_slot ───────────────────────────────
def test_book_appointment_nonexistent_slot_returns_slot_not_found(api):
    """PRD §2.5: "Path identifiers are validated left-to-right, and body foreign keys are
    then validated in their declared order. The first identifier that does not resolve to
    an existing resource causes the request to be rejected with the matching not-found
    error (... ERR_SLOT_NOT_FOUND ...), all returned with HTTP 404."
    PRD §2.6: "For booking, the optimistic-concurrency check (priority 5) runs before any
    slot capacity or slot-state business check."

    Booking with a nonexistent slot_id (existence check precedes the OCC version check)
    -> ERR_SLOT_NOT_FOUND.

    Design: Corner/errors/book_appointment_nonexistent_slot_returns_slot_not_found
    """
    center = create_center(clock=None)
    donor = create_donor(center["id"], full_name="NoSlot Donor")
    real_slot = create_slot(center["id"], donation_type="WHOLE",
                           starts_at="2025-01-02T08:00:00.000Z", ends_at="2025-01-02T18:00:00.000Z", capacity=5)
    res = api.create_appointment(
        {"donor_id": donor["id"], "slot_id": "11111111-1111-4111-8111-111111111111",
         "expected_slot_version": real_slot["version"]}, NURSE)
    validate_error(res, "ERR_SLOT_NOT_FOUND", expected_status=404)
