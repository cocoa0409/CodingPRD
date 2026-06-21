"""Boundary precision: the vaccine re-dose interval at exactly == interval (allowed)
versus one day under (rejected), and the empty-billable-set boundary on invoice finalize.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, assert_vaccination,
    create_household, create_patient,
    create_appointment, appointment_check_in, appointment_begin_exam, appointment_complete,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


class TestVaccineIntervalBoundary:
    """== interval is allowed; strictly < interval is rejected (PRD 3.4)."""

    def test_exact_interval_allowed_and_next_due_computed(self, api):
        """PRD 3.4: "a gap exactly equal to the interval is allowed, and any larger gap is
        allowed." and "The `next_due_at` is the `administered_at` plus the code's interval
        in days."

        Prior RABIES 2025-06-01; new RABIES exactly 365 days later 2026-06-01 is accepted
        with next_due_at 2027-06-01.

        Design: Difficulty/boundary_precision_check/vaccine_interval_exact_boundary_allows_equal_days
        """
        hh = create_household("Cole")
        _, pat = create_patient(household_id=hh["id"], name="Sky",
                                species="DOG", weight_kg=22)
        validate_success(api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2025-06-01T10:00:00Z",
        }, VETERINARIAN), 201)
        res = api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2026-06-01T10:00:00Z",
        }, VETERINARIAN)
        vax = validate_success(res, 201)
        assert_vaccination(vax)
        assert vax["next_due_at"][:10] == "2027-06-01", (
            f"Expected next_due 2027-06-01, got {vax['next_due_at']}")

    def test_one_day_under_interval_rejected(self, api):
        """PRD 3.4: "If the gap between the new dose's `administered_at` and that prior
        dose's `administered_at` is strictly fewer than the code's interval in days, the
        dose is rejected with `ERR_VACCINE_INTERVAL`".

        Prior RABIES 2025-06-01; new RABIES at 364 days (2026-05-31) is rejected.

        Design: Difficulty/boundary_precision_check/vaccine_interval_exact_boundary_allows_equal_days
        """
        hh = create_household("Cole2")
        _, pat = create_patient(household_id=hh["id"], name="Cloud",
                                species="DOG", weight_kg=22)
        validate_success(api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2025-06-01T10:00:00Z",
        }, VETERINARIAN), 201)
        res = api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2026-05-31T10:00:00Z",
        }, VETERINARIAN)
        validate_error(res, "ERR_VACCINE_INTERVAL", expected_status=422)


class TestInvoiceEmptyBillableSet:
    """An empty actual set on finalize is rejected (PRD 3.11)."""

    def test_completed_appointment_with_no_billable_items_rejected(self, api):
        """PRD 3.11: "there must be at least one rendered, billable item — an administered
        vaccination, a `RESULTED` lab order, or a `DONE` surgery — and an empty actual set
        is refused with `ERR_NO_BILLABLE_ITEMS`."

        A COMPLETED appointment with no labs/surgeries/vaccinations is rejected on finalize.

        Design: Difficulty/boundary_precision_check/invoice_empty_billable_set_rejected
        """
        hh = validate_success(api.create_household({"account_name": "Frost"}, RECEPTIONIST), 201)
        v0 = hh["version"]
        _, pat = create_patient(household_id=hh["id"], name="Pip",
                                species="RABBIT", weight_kg=2)
        appt = create_appointment(pat["id"], scheduled_start="2026-07-06T09:00:00Z",
                                  scheduled_end="2026-07-06T09:30:00Z", visit_reason="Check")
        appointment_check_in(appt["id"])
        appointment_begin_exam(appt["id"])
        appointment_complete(appt["id"])
        res = api.create_invoice({
            "household_id": hh["id"], "appointment_id": appt["id"],
            "expected_household_version": v0,
        }, PRACTICE_MANAGER)
        validate_error(res, "ERR_NO_BILLABLE_ITEMS", expected_status=422)

    def test_finalize_succeeds_once_one_billable_item_exists(self, api):
        """PRD 3.11: "there must be at least one rendered, billable item — an administered
        vaccination, a `RESULTED` lab order, or a `DONE` surgery".

        Adding one administered vaccination before completion makes the actual set
        non-empty, so finalize succeeds (the boundary's other side).

        Design: Difficulty/boundary_precision_check/invoice_empty_billable_set_rejected
        """
        hh = validate_success(api.create_household({"account_name": "Frost2"}, PRACTICE_MANAGER), 201)
        _, pat = create_patient(household_id=hh["id"], name="Pip2",
                                species="RABBIT", weight_kg=2)
        appt = create_appointment(pat["id"], scheduled_start="2026-06-01T09:00:00Z",
                                  scheduled_end="2026-06-01T09:30:00Z", visit_reason="Check")
        appointment_check_in(appt["id"])
        appointment_begin_exam(appt["id"])
        validate_success(api.create_vaccination({
            "patient_id": pat["id"], "vaccine_code": "RABIES",
            "administered_at": "2026-06-01T09:15:00Z",
        }, VETERINARIAN), 201)
        appointment_complete(appt["id"])
        hh_now = validate_success(api.get_household(hh["id"], PRACTICE_MANAGER), 200)
        res = api.create_invoice({
            "household_id": hh["id"], "appointment_id": appt["id"],
            "expected_household_version": hh_now["version"],
        }, PRACTICE_MANAGER)
        validate_success(res, 201)
