"""Cross-entity state dependencies (surgery->appointment, prescription->patient) and
isolated business-safety rejections (vaccine interval).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_household, create_patient, create_operatory,
    create_estimate, present_estimate, approve_estimate,
    create_appointment, appointment_check_in,
    create_prescription,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


class TestSurgeryStartRequiresAppointmentInExam:
    """Surgery start needs the parent appointment IN_EXAM (PRD 3.8)."""

    def _setup_booked_surgery_on_checked_in_appointment(self, api):
        operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-4")
        hh = create_household("Otto")
        _, pat = create_patient(household_id=hh["id"], name="Gus",
                                species="DOG", weight_kg=14)
        est = create_estimate(pat["id"], line_items=[
            {"service_code": "SURG", "qty": 1, "unit_price_cents": 30000, "eligible_for_plan_discount": False}],
            deposit_required_cents=0)
        present_estimate(est["id"])
        approve_estimate(est["id"])
        appt = create_appointment(pat["id"], scheduled_start="2026-07-07T09:00:00Z",
                                  scheduled_end="2026-07-07T11:00:00Z", visit_reason="Surgery")
        appointment_check_in(appt["id"])  # CHECKED_IN, NOT begin-exam
        res = api.create_surgery({
            "appointment_id": appt["id"], "operatory_id": operatory["id"],
            "estimate_id": est["id"], "procedure_name": "Mass removal",
            "window_start": "2026-07-07T09:00:00Z",
            "window_end": "2026-07-07T10:00:00Z",
        }, VETERINARIAN)
        surgery = validate_success(res, 201)
        return appt, surgery

    def test_start_rejected_when_appointment_only_checked_in(self, api):
        """PRD 3.8: "starting requires the surgery to be `BOOKED` ... and, as a
        cross-entity dependency from the surgery to its appointment, requires the parent
        appointment to be `IN_EXAM` (else `ERR_APPOINTMENT_NOT_IN_EXAM`)."

        Design: Difficulty/cross_entity_state_dependency/surgery_start_requires_appointment_in_exam
        """
        appt, surgery = self._setup_booked_surgery_on_checked_in_appointment(api)
        res = api.transition_surgery(surgery["id"], {"action": "start"}, VETERINARIAN)
        validate_error(res, "ERR_APPOINTMENT_NOT_IN_EXAM", expected_status=409)

    def test_surgery_remains_booked_after_rejected_start(self, api):
        """PRD 3.8: "A new surgery opens in `BOOKED`" and the start rejection leaves the
        surgery's own state valid (BOOKED) — the rejection comes from the sibling
        appointment's state, so the surgery is unchanged.

        Design: Difficulty/cross_entity_state_dependency/surgery_start_requires_appointment_in_exam
        """
        appt, surgery = self._setup_booked_surgery_on_checked_in_appointment(api)
        api.transition_surgery(surgery["id"], {"action": "start"}, VETERINARIAN)
        sg = validate_success(api.get_surgery(surgery["id"], VETERINARIAN), 200)
        assert sg["status"] == "BOOKED", f"Expected BOOKED unchanged, got {sg['status']}"


class TestPrescriptionRefillRequiresPatientActive:
    """Refilling a prescription needs the patient ACTIVE (PRD 3.5)."""

    def _setup_rx_on_deactivated_patient(self, api):
        hh = create_household("Dey")
        _, pat = create_patient(household_id=hh["id"], name="Rua",
                                species="CAT", weight_kg=5)
        rx = create_prescription(pat["id"], refills_authorized=2, is_controlled=False,
                                 drug_name="Amoxicillin")
        validate_success(api.deactivate_patient(pat["id"], RECEPTIONIST), 200)
        return pat, rx

    def test_refill_rejected_when_patient_inactive(self, api):
        """PRD 3.5: "as a cross-entity dependency from the prescription to its pet,
        requires the patient to be `ACTIVE` (otherwise `ERR_PATIENT_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/prescription_refill_requires_patient_active
        """
        pat, rx = self._setup_rx_on_deactivated_patient(api)
        res = api.refill_prescription(rx["id"], VETERINARIAN)
        validate_error(res, "ERR_PATIENT_NOT_ACTIVE", expected_status=409)

    def test_prescription_unchanged_after_rejected_refill(self, api):
        """PRD 3.5: "A new prescription opens `ACTIVE`, with `refills_used` at zero." The
        rejected refill (patient INACTIVE) leaves refills_used unchanged at 0.

        Design: Difficulty/cross_entity_state_dependency/prescription_refill_requires_patient_active
        """
        pat, rx = self._setup_rx_on_deactivated_patient(api)
        api.refill_prescription(rx["id"], VETERINARIAN)
        rx_after = validate_success(api.get_prescription(rx["id"], VETERINARIAN), 200)
        assert rx_after["refills_used"] == 0, (
            f"Expected refills_used unchanged at 0, got {rx_after['refills_used']}")


class TestVaccineIntervalSafety:
    """A same-code dose strictly within the interval is rejected (PRD 3.4)."""

    def test_rabies_one_day_after_prior_dose_rejected(self, api):
        """PRD 3.4: "If the gap between the new dose's `administered_at` and that prior
        dose's `administered_at` is strictly fewer than the code's interval in days, the
        dose is rejected with `ERR_VACCINE_INTERVAL`".

        A RABIES dose 1 day after the prior dose (well under 365) is rejected.

        Design: Difficulty/priority_pair_validation_conflict/vaccine_safety_interval_beats_kennel_temporal_unrelated_path
        """
        hh = create_household("Reed")
        _, pat = create_patient(household_id=hh["id"], name="Bolt",
                                species="DOG", weight_kg=18)
        validate_success(api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2025-06-01T10:00:00Z",
        }, VETERINARIAN), 201)
        res = api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2025-06-02T10:00:00Z",
        }, VETERINARIAN)
        validate_error(res, "ERR_VACCINE_INTERVAL", expected_status=422)

    def test_different_code_within_interval_allowed(self, api):
        """PRD 3.4: "the system finds the patient's latest prior dose of the same
        `vaccine_code`" — the interval check is per vaccine_code, so a different-code dose
        soon after is accepted.

        A DHPP dose 1 day after a RABIES dose is allowed (different codes; no prior DHPP).

        Design: Difficulty/priority_pair_validation_conflict/vaccine_safety_interval_beats_kennel_temporal_unrelated_path
        """
        hh = create_household("Reed2")
        _, pat = create_patient(household_id=hh["id"], name="Dash",
                                species="DOG", weight_kg=18)
        validate_success(api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2025-06-01T10:00:00Z",
        }, VETERINARIAN), 201)
        res = api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "DHPP",
            "administered_at": "2025-06-02T10:00:00Z",
        }, VETERINARIAN)
        validate_success(res, 201)
