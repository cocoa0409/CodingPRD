"""Transitive cascades: appointment-cancel (depth-3: surgery -> operatory release +
deposit refund) and patient-deceased (prescription void + boarding cancel), plus the
immediate-consistency corner case.
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_household, create_patient, create_operatory, create_kennel,
    create_estimate, present_estimate, approve_estimate, post_deposit,
    create_appointment, appointment_check_in, appointment_begin_exam,
    create_appointment_in_exam, book_surgery, create_prescription, refill_prescription,
    reserve_boarding, place_lab_order,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


class TestAppointmentCancelCascade:
    """Cancelling an appointment cascades to surgery, operatory, and household credit."""

    def _setup_booked_surgery_with_deposit(self, api):
        operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-3")
        hh = create_household("Brar")
        _, pat = create_patient(household_id=hh["id"], name="Duke",
                                species="DOG", weight_kg=10)
        est = create_estimate(pat["id"], line_items=[
            {"service_code": "SURG", "qty": 1, "unit_price_cents": 26000, "eligible_for_plan_discount": False}],
            deposit_required_cents=30000)
        post_deposit(hh["id"], 30000, hh["version"], estimate_id=est["id"])
        present_estimate(est["id"])
        approve_estimate(est["id"])
        appt = create_appointment(pat["id"], scheduled_start="2026-07-04T09:00:00Z",
                                  scheduled_end="2026-07-04T11:00:00Z", visit_reason="Surgery")
        appointment_check_in(appt["id"])
        appointment_begin_exam(appt["id"])
        surgery = book_surgery(appt["id"], operatory["id"], est["id"],
                               window_start="2026-07-04T09:00:00Z",
                               window_end="2026-07-04T10:00:00Z", procedure_name="Neuter")
        return hh, operatory, appt, surgery

    def test_cancel_cascades_surgery_and_operatory_release(self, api):
        """PRD 3.3: "Every surgery on the appointment in `BOOKED` or `IN_PROGRESS` is
        itself cancelled (hop one); each cancelled surgery releases its operatory booking
        by decrementing that operatory's `booked_minutes` by the surgery's window length
        in minutes (hop two)".

        Design: Difficulty/transitive_cascade/appointment_cancel_cascades_surgery_operatory_and_deposit_refund
        """
        hh, operatory, appt, surgery = self._setup_booked_surgery_with_deposit(api)
        res = api.transition_appointment(appt["id"], {"action": "cancel"}, RECEPTIONIST)
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"
        sg = validate_success(api.get_surgery(surgery["id"], VETERINARIAN), 200)
        assert sg["status"] == "CANCELLED", f"Expected surgery CANCELLED, got {sg['status']}"
        op = validate_success(api.get_operatory(operatory["id"], PRACTICE_MANAGER), 200)
        assert op["booked_minutes"] == 0, (
            f"Expected booked_minutes 0 after release, got {op['booked_minutes']}")

    def test_cancel_refunds_deposit_to_household_credit(self, api):
        """PRD 3.3: "each cancelled surgery refunds its `deposit_consumed_cents` back to
        the funding estimate's household by adding it to that household's
        `account_credit_cents` and bumping that household's `version` by one (hop three),
        conserving credit."

        Deposit 30000, consumed 26000 (credit 4000) -> on cancel refunds 26000 -> credit
        30000; surgery deposit_consumed reset to 0.

        Design: Difficulty/transitive_cascade/appointment_cancel_cascades_surgery_operatory_and_deposit_refund
        """
        hh, operatory, appt, surgery = self._setup_booked_surgery_with_deposit(api)
        validate_success(api.transition_appointment(appt["id"], {"action": "cancel"}, RECEPTIONIST), 200)
        hh_after = validate_success(api.get_household(hh["id"], PRACTICE_MANAGER), 200)
        assert hh_after["account_credit_cents"] == 30000, (
            f"Expected credit 30000 after refund, got {hh_after['account_credit_cents']}")
        sg = validate_success(api.get_surgery(surgery["id"], VETERINARIAN), 200)
        assert sg["deposit_consumed_cents"] == 0, (
            f"Expected deposit_consumed 0, got {sg['deposit_consumed_cents']}")


class TestPatientDeceasedCascade:
    """Marking a patient deceased voids prescriptions and cancels boarding stays."""

    def _setup_patient_with_rx_and_boarding(self, api):
        ken = create_kennel(capacity=2, name="K-1")
        hh = create_household("Mora")
        _, pat = create_patient(household_id=hh["id"], name="Old Tom",
                                species="CAT", weight_kg=6)
        rx = create_prescription(pat["id"], refills_authorized=3, is_controlled=True,
                                 drug_name="Gabapentin")
        refill_prescription(rx["id"])  # refills_used -> 1
        bs = reserve_boarding(pat["id"], ken["id"],
                              check_in_date="2026-07-05T00:00:00Z",
                              check_out_date="2026-07-07T00:00:00Z",
                              nightly_rate_cents=5000)
        return pat, rx, bs

    def test_deceased_voids_active_prescription_and_restores_refills(self, api):
        """PRD 3.1: "every prescription for that patient currently in status `ACTIVE` is
        transitioned to `VOIDED`. Then (hop two), each prescription that was just voided
        restores its remaining refills to the full authorized count — its `refills_used`
        is reset to zero".

        Design: Difficulty/transitive_cascade/patient_deceased_cascades_prescription_void_and_boarding_cancel
        """
        pat, rx, bs = self._setup_patient_with_rx_and_boarding(api)
        res = api.mark_patient_deceased(pat["id"], VETERINARIAN)
        deceased = validate_success(res, 200)
        assert deceased["status"] == "DECEASED"
        rx_after = validate_success(api.get_prescription(rx["id"], VETERINARIAN), 200)
        assert rx_after["status"] == "VOIDED", f"Expected VOIDED, got {rx_after['status']}"
        assert rx_after["refills_used"] == 0, (
            f"Expected refills_used reset to 0, got {rx_after['refills_used']}")

    def test_deceased_cancels_reserved_boarding_stay(self, api):
        """PRD 3.1: "every boarding stay for that patient in status `RESERVED` or
        `CHECKED_IN` is transitioned to `CANCELLED`, and each such cancellation releases
        that stay's kennel occupancy across the days it spanned".

        Design: Difficulty/transitive_cascade/patient_deceased_cascades_prescription_void_and_boarding_cancel
        """
        pat, rx, bs = self._setup_patient_with_rx_and_boarding(api)
        validate_success(api.mark_patient_deceased(pat["id"], VETERINARIAN), 200)
        bs_after = validate_success(api.get_boarding_stay(bs["id"], VETERINARIAN), 200)
        assert bs_after["status"] == "CANCELLED", (
            f"Expected boarding CANCELLED, got {bs_after['status']}")


def test_cancel_cascades_lab_order_immediately(api):
    """PRD 3.10: "a lab order is also cancelled automatically when its parent appointment
    is cancelled, as part of that appointment's cascade." PRD 2.7: "all cascade effects of
    a single operation are applied together as part of that operation, and the response
    reflects the fully reconciled state."

    Cancelling an IN_EXAM appointment with an ORDERED lab order makes the lab order
    CANCELLED, observable immediately on a GET.

    Design: Corner/consistency_model/cascade_visible_in_same_request_immediate
    """
    hh = create_household("Imm")
    _, pat = create_patient(household_id=hh["id"], name="ImmPet",
                            species="DOG", weight_kg=10)
    appt = create_appointment_in_exam(pat["id"],
                                      scheduled_start="2026-08-12T09:00:00Z",
                                      scheduled_end="2026-08-12T10:00:00Z")
    lo = place_lab_order(appt["id"], order_type="BIOPSY", fee_cents=9000)
    validate_success(api.transition_appointment(appt["id"], {"action": "cancel"}, RECEPTIONIST), 200)
    lo_after = validate_success(api.get_lab_order(lo["id"], VETERINARIAN), 200)
    assert lo_after["status"] == "CANCELLED", (
        f"Expected lab order CANCELLED, got {lo_after['status']}")
