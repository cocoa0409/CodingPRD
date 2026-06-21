"""Compensating invariants: a surgery cancel refunds the committed deposit exactly
(monetary conservation), and a patient-deceased void restores the authorized refill
count exactly (discrete-count conservation).
"""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_household, create_patient, create_operatory,
    create_estimate, present_estimate, approve_estimate, post_deposit,
    create_appointment, appointment_check_in, appointment_begin_exam,
    book_surgery, create_prescription, refill_prescription,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


class TestDepositRefundConservesCredit:
    """Book (debit) then cancel (refund) nets to zero drift on account_credit_cents."""

    def _setup_booked_surgery(self, api):
        operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-6")
        hh = create_household("Knox")
        _, pat = create_patient(household_id=hh["id"], name="Tess",
                                species="DOG", weight_kg=10)
        est = create_estimate(pat["id"], line_items=[
            {"service_code": "SURG", "qty": 1, "unit_price_cents": 26000, "eligible_for_plan_discount": False}],
            deposit_required_cents=30000)
        post_deposit(hh["id"], 30000, hh["version"], estimate_id=est["id"])
        present_estimate(est["id"])
        approve_estimate(est["id"])
        appt = create_appointment(pat["id"], scheduled_start="2026-07-09T09:00:00Z",
                                  scheduled_end="2026-07-09T11:00:00Z", visit_reason="Surgery")
        appointment_check_in(appt["id"])
        appointment_begin_exam(appt["id"])
        surgery = book_surgery(appt["id"], operatory["id"], est["id"],
                               window_start="2026-07-09T09:00:00Z",
                               window_end="2026-07-09T10:00:00Z", procedure_name="Neuter")
        return hh, surgery

    def test_surgery_cancel_restores_full_household_credit(self, api):
        """PRD 3.8: "if `deposit_consumed_cents` is greater than zero — refunds it to the
        funding estimate's household by adding it back to that household's
        `account_credit_cents` ... and then resets `deposit_consumed_cents` to zero."

        Deposit 30000; booking commits 26000 (credit 4000); cancel refunds 26000 ->
        credit returns to 30000, as if never booked.

        Design: Difficulty/compensating_invariant/deposit_refund_conserves_household_credit
        """
        hh, surgery = self._setup_booked_surgery(api)
        before = validate_success(api.get_household(hh["id"], PRACTICE_MANAGER), 200)
        assert before["account_credit_cents"] == 4000, (
            f"Expected credit 4000 after booking, got {before['account_credit_cents']}")
        validate_success(api.transition_surgery(surgery["id"], {"action": "cancel"}, VETERINARIAN), 200)
        after = validate_success(api.get_household(hh["id"], PRACTICE_MANAGER), 200)
        assert after["account_credit_cents"] == 30000, (
            f"Expected credit restored to 30000, got {after['account_credit_cents']}")

    def test_surgery_cancel_resets_deposit_consumed(self, api):
        """PRD 3.8: "and then resets `deposit_consumed_cents` to zero."

        After cancel, the surgery's deposit_consumed_cents is 0.

        Design: Difficulty/compensating_invariant/deposit_refund_conserves_household_credit
        """
        hh, surgery = self._setup_booked_surgery(api)
        res = api.transition_surgery(surgery["id"], {"action": "cancel"}, VETERINARIAN)
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["deposit_consumed_cents"] == 0, (
            f"Expected deposit_consumed 0, got {cancelled['deposit_consumed_cents']}")


class TestRefillVoidConservesCount:
    """Dispensing then voiding (via patient deceased) returns refills_used to 0."""

    def _setup_rx_with_two_refills(self, api):
        hh = create_household("Lowe")
        _, pat = create_patient(household_id=hh["id"], name="Max",
                                species="DOG", weight_kg=25)
        rx = create_prescription(pat["id"], refills_authorized=3, is_controlled=False,
                                 drug_name="Tramadol")
        refill_prescription(rx["id"])
        refill_prescription(rx["id"])
        return pat, rx

    def test_void_restores_refills_used_to_zero(self, api):
        """PRD 3.5: "the void restores the prescription's `refills_used` to zero so that
        its remaining refills return to the full `refills_authorized` — the authorized
        count is conserved through the void rather than consumed."

        After 2 of 3 refills then patient-deceased void: status VOIDED, refills_used 0.

        Design: Difficulty/compensating_invariant/refill_void_conserves_authorized_refill_count
        """
        pat, rx = self._setup_rx_with_two_refills(api)
        validate_success(api.mark_patient_deceased(pat["id"], VETERINARIAN), 200)
        rx_after = validate_success(api.get_prescription(rx["id"], VETERINARIAN), 200)
        assert rx_after["status"] == "VOIDED", f"Expected VOIDED, got {rx_after['status']}"
        assert rx_after["refills_used"] == 0, (
            f"Expected refills_used 0, got {rx_after['refills_used']}")

    def test_authorized_count_unchanged_through_void(self, api):
        """PRD 3.5: "its remaining refills return to the full `refills_authorized`".

        refills_authorized stays 3 across dispense-then-void; the budget is conserved.

        Design: Difficulty/compensating_invariant/refill_void_conserves_authorized_refill_count
        """
        pat, rx = self._setup_rx_with_two_refills(api)
        validate_success(api.mark_patient_deceased(pat["id"], VETERINARIAN), 200)
        rx_after = validate_success(api.get_prescription(rx["id"], VETERINARIAN), 200)
        assert rx_after["refills_authorized"] == 3, (
            f"Expected refills_authorized 3, got {rx_after['refills_authorized']}")
