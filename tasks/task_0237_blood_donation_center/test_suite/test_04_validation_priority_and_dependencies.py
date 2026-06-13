"""Priority-pair conflict and cross-entity-state-dependency difficulty tests.

Queue A:
  priority_pair_validation_conflict:
    - checkin_state_before_eligibility
    - donation_screening_before_plasma_cap
  cross_entity_state_dependency:
    - appointment_checkin_blocked_by_donor_deferral
    - donation_release_blocked_by_severe_adverse_reaction
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    create_deferral_payload, create_donation_payload, create_test_result_payload,
    create_blood_unit_payload, create_adverse_reaction_payload,
    setup_scheduled_appointment, setup_checked_in_appointment, setup_labeled_unit,
    raise_deferral, log_adverse_reaction,
    TEST_USERS,
)

NURSE = TEST_USERS["intake_nurse_headers"]
LAB = TEST_USERS["lab_technician_headers"]


# ─── checkin_state_before_eligibility ─────────────────────────────────────────
def test_checkin_state_error_precedes_eligibility_error(api):
    """PRD §3.4: "Checking a donor in is an IntakeNurse action that advances the
    appointment from SCHEDULED to CHECKED_IN. It is gated by three preconditions evaluated
    in order. The appointment must be SCHEDULED, else ERR_APPOINTMENT_NOT_SCHEDULED. The
    donor's eligibility_status must equal ELIGIBLE at the center's current_utc, else
    ERR_DONOR_NOT_ELIGIBLE (HTTP 403)."

    A CANCELLED appointment of a TEMP_DEFERRED donor violates both; the state check
    (evaluated first) wins with ERR_APPOINTMENT_NOT_SCHEDULED.

    Design: Difficulty/priority_pair_validation_conflict/checkin_state_before_eligibility
    """
    center, donor, slot, appt = setup_scheduled_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"blood_type": "A_POS", "weight_kg": 62})
    get_success_data(api.cancel_appointment(appt["id"], NURSE))
    raise_deferral(donor["id"], category="TRAVEL", kind="TEMPORARY",
                   reason="endemic region trip", duration_days=21)

    res = api.check_in_appointment(appt["id"], NURSE)
    validate_error(res, "ERR_APPOINTMENT_NOT_SCHEDULED", expected_status=409)


def test_checkin_on_scheduled_deferred_donor_returns_eligibility_error(api):
    """PRD §3.4: "The donor's eligibility_status must equal ELIGIBLE at the center's
    current_utc, else ERR_DONOR_NOT_ELIGIBLE (HTTP 403)."

    With the state precondition satisfied (appointment still SCHEDULED), the same deferred
    donor surfaces the eligibility error — confirming it is the next gate after state.

    Design: Difficulty/priority_pair_validation_conflict/checkin_state_before_eligibility
    """
    center, donor, slot, appt = setup_scheduled_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"blood_type": "A_POS", "weight_kg": 62})
    raise_deferral(donor["id"], category="TRAVEL", kind="TEMPORARY",
                   reason="endemic region trip", duration_days=21)

    res = api.check_in_appointment(appt["id"], NURSE)
    validate_error(res, "ERR_DONOR_NOT_ELIGIBLE", expected_status=403)


# ─── donation_screening_before_plasma_cap ─────────────────────────────────────
def test_collection_screening_error_precedes_plasma_cap_error(api):
    """PRD §3.6: "Its preconditions are evaluated in order: the appointment must be
    CHECKED_IN, else ERR_APPOINTMENT_NOT_CHECKED_IN; a health screening with outcome of
    PASS must exist for the appointment, else ERR_SCREENING_NOT_PASSED; and for a PLASMA
    donation the two plasma caps of §3.5 are enforced (the per-collection band cap first,
    yielding ERR_PLASMA_VOLUME_EXCEEDED, then the rolling annual cap ...)."

    A CHECKED_IN PLASMA appointment with NO screening AND an over-cap 900 mL collection
    surfaces ERR_SCREENING_NOT_PASSED (evaluated before the plasma cap).

    Design: Difficulty/priority_pair_validation_conflict/donation_screening_before_plasma_cap
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="PLASMA",
        donor_overrides={"weight_kg": 60, "blood_type": "O_POS"})

    res = api.create_donation(appt["id"], create_donation_payload(volume_ml=900), NURSE)
    validate_error(res, "ERR_SCREENING_NOT_PASSED", expected_status=409)


def test_collection_over_cap_with_passing_screening_returns_plasma_cap_error(api):
    """PRD §3.5: "The collection's volume_ml must not exceed the applicable band cap,
    otherwise ERR_PLASMA_VOLUME_EXCEEDED (HTTP 422) is returned."

    With the screening precondition satisfied (a PASS screening exists), the same over-cap
    900 mL collection for a 60 kg donor (cap 690) surfaces the plasma cap error —
    confirming it is the next gate after screening.

    Design: Difficulty/priority_pair_validation_conflict/donation_screening_before_plasma_cap
    """
    center, donor, slot, appt = setup_checked_in_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="PLASMA",
        donor_overrides={"weight_kg": 60, "blood_type": "O_POS"})
    get_success_data(api.create_health_screening(
        {"appointment_id": appt["id"], "hemoglobin_g_dl": 13.5, "systolic_bp": 120,
         "pulse_bpm": 70, "weight_kg": 60, "recent_travel_risk": False,
         "disqualifying_medication": False}, NURSE))

    res = api.create_donation(appt["id"], create_donation_payload(volume_ml=900), NURSE)
    validate_error(res, "ERR_PLASMA_VOLUME_EXCEEDED", expected_status=422)


# ─── appointment_checkin_blocked_by_donor_deferral ────────────────────────────
def test_checkin_blocked_when_donor_temp_deferred(api):
    """PRD §3.4: "The donor's eligibility_status must equal ELIGIBLE at the center's
    current_utc, else ERR_DONOR_NOT_ELIGIBLE (HTTP 403)."
    PRD §3.2: "Raising a deferral recomputes the donor's eligibility_status to
    TEMP_DEFERRED or PERM_DEFERRED as appropriate."

    A donor with a SCHEDULED appointment is manually TEMP_DEFERRED; check-in fails on the
    cross-entity eligibility dependency and the appointment stays SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/appointment_checkin_blocked_by_donor_deferral
    """
    center, donor, slot, appt = setup_scheduled_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"blood_type": "B_POS", "weight_kg": 66})
    raise_deferral(donor["id"], category="MEDICATION", kind="TEMPORARY",
                   reason="on antibiotics", duration_days=14)

    res = api.check_in_appointment(appt["id"], NURSE)
    validate_error(res, "ERR_DONOR_NOT_ELIGIBLE", expected_status=403)

    donor_after = validate_success(api.get_donor(donor["id"], NURSE), 200)
    assert donor_after["eligibility_status"] == "TEMP_DEFERRED"
    appt_after = validate_success(api.get_appointment(appt["id"], NURSE), 200)
    assert appt_after["status"] == "SCHEDULED", "transition rejected, appointment unchanged"


def test_checkin_succeeds_for_eligible_donor_with_no_deferral(api):
    """PRD §3.4: "It is gated by three preconditions evaluated in order. The appointment
    must be SCHEDULED, else ERR_APPOINTMENT_NOT_SCHEDULED. The donor's eligibility_status
    must equal ELIGIBLE at the center's current_utc, else ERR_DONOR_NOT_ELIGIBLE (HTTP 403)."

    The positive control for the cross-entity dependency: an ELIGIBLE donor with no
    deferral checks in successfully.

    Design: Difficulty/cross_entity_state_dependency/appointment_checkin_blocked_by_donor_deferral
    """
    center, donor, slot, appt = setup_scheduled_appointment(
        center_clock="2025-01-01T00:00:00.000Z", donation_type="WHOLE",
        donor_overrides={"blood_type": "B_POS", "weight_kg": 66})

    checked_in = validate_success(api.check_in_appointment(appt["id"], NURSE), 200)
    assert checked_in["status"] == "CHECKED_IN"


# ─── donation_release_blocked_by_severe_adverse_reaction ──────────────────────
def test_negative_test_blocked_by_severe_adverse_reaction(api):
    """PRD §3.6: "On a NEGATIVE result, releasing additionally requires that no SEVERE
    adverse reaction exists for the donation; if one does, the release is blocked with
    ERR_SEVERE_REACTION_BLOCKS_RELEASE."

    A COLLECTED donation carrying a SEVERE reaction cannot release even on a NEGATIVE
    panel; the donation stays COLLECTED.

    Design: Difficulty/cross_entity_state_dependency/donation_release_blocked_by_severe_adverse_reaction
    """
    center, donor, slot, appt, donation, unit = setup_labeled_unit(
        din="DIN-SEV-001", donor_overrides={"blood_type": "AB_NEG", "weight_kg": 74})
    log_adverse_reaction(donation["id"], severity="SEVERE", symptom="syncope with injury")

    res = api.create_test_result(donation["id"], create_test_result_payload(panel_outcome="NEGATIVE"), LAB)
    validate_error(res, "ERR_SEVERE_REACTION_BLOCKS_RELEASE", expected_status=409)

    don_after = validate_success(api.get_donation(donation["id"], LAB), 200)
    assert don_after["status"] == "COLLECTED", "release blocked, donation stays COLLECTED"


def test_negative_test_releases_when_only_mild_reaction_present(api):
    """PRD §3.6: "When the panel is NEGATIVE and no severe reaction blocks it, the
    donation transitions from COLLECTED to RELEASABLE ..."

    A MILD reaction does not block release: the same NEGATIVE panel sends the donation to
    RELEASABLE, confirming only SEVERE severity gates the cross-entity dependency.

    Design: Difficulty/cross_entity_state_dependency/donation_release_blocked_by_severe_adverse_reaction
    """
    center, donor, slot, appt, donation, unit = setup_labeled_unit(
        din="DIN-MILD-001", donor_overrides={"blood_type": "AB_NEG", "weight_kg": 74})
    log_adverse_reaction(donation["id"], severity="MILD", symptom="light dizziness")

    validate_success(api.create_test_result(
        donation["id"], create_test_result_payload(panel_outcome="NEGATIVE"), LAB), 201)
    don_after = validate_success(api.get_donation(donation["id"], LAB), 200)
    assert don_after["status"] == "RELEASABLE", "MILD reaction does not block release"
