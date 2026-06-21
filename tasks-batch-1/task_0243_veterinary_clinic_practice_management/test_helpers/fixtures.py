"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a fresh, empty database (the harness restarts the server
before every test), so every fixture builds its preconditions from scratch using
only PRD-declared endpoints. Fixtures use get_success_data() (lenient validator)
so setup failures surface as clear "Setup failed" errors rather than confusing
assertion failures.

Role usage follows PRD 2.1 (purely role-based, opaque identities):
  - Receptionist: households, owners, patients, deposits, appointments, boarding,
    estimate create/decline/approve, appointment check-in/cancel/no-show.
  - Veterinarian: vaccinations, prescriptions, surgery, lab orders, mark-deceased,
    estimate present/revise, appointment begin-exam/reschedule/complete.
  - PracticeManager: operatories, kennels, invoices, estimate expire.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_operatory_payload, create_kennel_payload, create_household_payload,
    create_deposit_payload, create_patient_payload, create_wellness_plan_payload,
    create_appointment_payload, create_vaccination_payload, create_prescription_payload,
    create_estimate_payload, create_surgery_payload, create_boarding_stay_payload,
    create_lab_order_payload, create_invoice_payload,
)
from .test_users import TEST_USERS

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


# ─── Tier 1: Base entities ────────────────────────────────────────────────────

def create_household(account_name="The Test Family"):
    """Create a household; returns the household dict (version=1, credit=0)."""
    return get_success_data(api_client.create_household(
        create_household_payload(account_name=account_name), RECEPTIONIST))


def create_patient(household_id=None, **patient_overrides):
    """Create a household (if needed) + one ACTIVE patient. Returns (household, patient)."""
    if household_id is None:
        hh = create_household()
        household_id = hh["id"]
    else:
        hh = None
    pat = get_success_data(api_client.create_patient(
        create_patient_payload(household_id, **patient_overrides), RECEPTIONIST))
    return hh, pat


def create_operatory(cleanup_buffer_minutes=30, name="OR"):
    return get_success_data(api_client.create_operatory(
        create_operatory_payload(name=name, cleanup_buffer_minutes=cleanup_buffer_minutes),
        PRACTICE_MANAGER))


def create_kennel(capacity=2, name="Kennel"):
    return get_success_data(api_client.create_kennel(
        create_kennel_payload(name=name, capacity=capacity), PRACTICE_MANAGER))


def create_wellness_plan(patient_id, tier="BASIC"):
    return get_success_data(api_client.create_wellness_plan(
        create_wellness_plan_payload(patient_id, tier=tier), RECEPTIONIST))


# ─── Tier 2: Deposits / household credit ──────────────────────────────────────

def post_deposit(household_id, amount_cents, expected_household_version,
                 estimate_id=None):
    """Post a deposit, optionally earmarked to an estimate. Returns the household dict."""
    extra = {}
    if estimate_id is not None:
        extra["estimate_id"] = estimate_id
    return get_success_data(api_client.create_deposit(
        create_deposit_payload(household_id, amount_cents, expected_household_version, **extra),
        RECEPTIONIST))


# ─── Tier 3: Estimate lifecycle ───────────────────────────────────────────────

def create_estimate(patient_id, line_items=None, deposit_required_cents=0):
    return get_success_data(api_client.create_estimate(
        create_estimate_payload(patient_id, line_items=line_items,
                                deposit_required_cents=deposit_required_cents),
        VETERINARIAN))


def present_estimate(estimate_id):
    return get_success_data(api_client.transition_estimate(
        estimate_id, {"action": "present"}, VETERINARIAN))


def approve_estimate(estimate_id):
    return get_success_data(api_client.transition_estimate(
        estimate_id, {"action": "approve"}, RECEPTIONIST))


def create_approved_estimate(patient_id, household_id, household_version,
                             line_items=None, deposit_required_cents=0,
                             deposit_amount_cents=None):
    """Create an estimate, optionally post a deposit, present, and approve it.

    Returns (estimate, household_version_after). If deposit_amount_cents is given
    the deposit is posted against the estimate before approval; the household
    version returned reflects the deposit bump (or the original if no deposit).
    """
    est = create_estimate(patient_id, line_items=line_items,
                          deposit_required_cents=deposit_required_cents)
    version_after = household_version
    if deposit_amount_cents is not None:
        hh = post_deposit(household_id, deposit_amount_cents, household_version,
                          estimate_id=est["id"])
        version_after = hh["version"]
    present_estimate(est["id"])
    approve_estimate(est["id"])
    return get_success_data(api_client.get_estimate(est["id"], VETERINARIAN)), version_after


# ─── Tier 4: Appointment lifecycle ────────────────────────────────────────────

def create_appointment(patient_id, scheduled_start="2026-07-01T09:00:00Z",
                       scheduled_end="2026-07-01T10:00:00Z", visit_reason="Visit"):
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(patient_id, scheduled_start=scheduled_start,
                                   scheduled_end=scheduled_end, visit_reason=visit_reason),
        RECEPTIONIST))


def appointment_check_in(appointment_id):
    return get_success_data(api_client.transition_appointment(
        appointment_id, {"action": "check-in"}, RECEPTIONIST))


def appointment_begin_exam(appointment_id):
    return get_success_data(api_client.transition_appointment(
        appointment_id, {"action": "begin-exam"}, VETERINARIAN))


def appointment_complete(appointment_id):
    return get_success_data(api_client.transition_appointment(
        appointment_id, {"action": "complete"}, VETERINARIAN))


def create_appointment_in_exam(patient_id, scheduled_start="2026-07-01T09:00:00Z",
                               scheduled_end="2026-07-01T12:00:00Z"):
    """Schedule -> check-in -> begin-exam. Returns the IN_EXAM appointment."""
    appt = create_appointment(patient_id, scheduled_start=scheduled_start,
                              scheduled_end=scheduled_end)
    appointment_check_in(appt["id"])
    return appointment_begin_exam(appt["id"])


# ─── Tier 5: Surgery lifecycle ────────────────────────────────────────────────

def book_surgery(appointment_id, operatory_id, estimate_id,
                 window_start="2026-07-01T09:00:00Z",
                 window_end="2026-07-01T10:00:00Z", procedure_name="Spay"):
    return get_success_data(api_client.create_surgery(
        create_surgery_payload(appointment_id, operatory_id, estimate_id,
                               window_start=window_start, window_end=window_end,
                               procedure_name=procedure_name),
        VETERINARIAN))


def surgery_start(surgery_id):
    return get_success_data(api_client.transition_surgery(
        surgery_id, {"action": "start"}, VETERINARIAN))


def surgery_complete(surgery_id):
    return get_success_data(api_client.transition_surgery(
        surgery_id, {"action": "complete"}, VETERINARIAN))


def setup_booked_surgery(weight_kg=10, deposit_required_cents=0,
                         deposit_amount_cents=None,
                         window_start="2026-07-01T09:00:00Z",
                         window_end="2026-07-01T10:00:00Z",
                         cleanup_buffer_minutes=30,
                         line_unit_price_cents=30000):
    """Full chain to one BOOKED surgery on an IN_EXAM appointment.

    operatory + household + patient + approved estimate (optionally deposit-funded)
    + IN_EXAM appointment + booked surgery.
    Returns dict with keys: operatory, household, patient, estimate, appointment,
    surgery, household_version (after booking).
    """
    operatory = create_operatory(cleanup_buffer_minutes=cleanup_buffer_minutes)
    hh = create_household()
    _, pat = create_patient(household_id=hh["id"], weight_kg=weight_kg)
    line_items = [{"service_code": "SURG", "qty": 1,
                   "unit_price_cents": line_unit_price_cents,
                   "eligible_for_plan_discount": False}]
    est, hv = create_approved_estimate(
        pat["id"], hh["id"], hh["version"], line_items=line_items,
        deposit_required_cents=deposit_required_cents,
        deposit_amount_cents=deposit_amount_cents)
    appt = create_appointment_in_exam(pat["id"],
                                      scheduled_start="2026-07-01T08:00:00Z",
                                      scheduled_end="2026-07-01T14:00:00Z")
    surgery = book_surgery(appt["id"], operatory["id"], est["id"],
                           window_start=window_start, window_end=window_end)
    hh_after = get_success_data(api_client.get_household(hh["id"], PRACTICE_MANAGER))
    return {
        "operatory": operatory,
        "household": hh_after,
        "patient": pat,
        "estimate": est,
        "appointment": appt,
        "surgery": surgery,
        "household_version": hh_after["version"],
    }


# ─── Tier 6: Lab order lifecycle ──────────────────────────────────────────────

def place_lab_order(appointment_id, order_type="BLOODWORK", fee_cents=6000):
    return get_success_data(api_client.create_lab_order(
        create_lab_order_payload(appointment_id, order_type=order_type, fee_cents=fee_cents),
        VETERINARIAN))


def lab_collect(lab_order_id):
    return get_success_data(api_client.transition_lab_order(
        lab_order_id, {"action": "collect"}, VETERINARIAN))


def lab_result(lab_order_id, result_text="Normal"):
    return get_success_data(api_client.transition_lab_order(
        lab_order_id, {"action": "result", "result_text": result_text}, VETERINARIAN))


def create_resulted_lab_order(appointment_id, fee_cents=6000,
                              order_type="BLOODWORK", result_text="Normal"):
    """Place -> collect -> result a lab order. Returns the RESULTED lab order."""
    lo = place_lab_order(appointment_id, order_type=order_type, fee_cents=fee_cents)
    lab_collect(lo["id"])
    return lab_result(lo["id"], result_text=result_text)


# ─── Tier 7: Prescription lifecycle ───────────────────────────────────────────

def create_prescription(patient_id, refills_authorized=2, is_controlled=False,
                        drug_name="Amoxicillin"):
    return get_success_data(api_client.create_prescription(
        create_prescription_payload(patient_id, refills_authorized=refills_authorized,
                                    is_controlled=is_controlled, drug_name=drug_name),
        VETERINARIAN))


def refill_prescription(prescription_id):
    return get_success_data(api_client.refill_prescription(prescription_id, VETERINARIAN))


# ─── Tier 8: Completed-appointment-ready-to-invoice ───────────────────────────

def setup_completed_appointment_with_lab(fee_cents=7000, household_role=PRACTICE_MANAGER):
    """Household + patient + appointment driven IN_EXAM with one RESULTED lab order,
    then COMPLETED. Returns dict: household, patient, appointment, lab_order,
    household_version (current). Suitable for invoice finalization tests.
    """
    hh = get_success_data(api_client.create_household(
        create_household_payload(account_name="Bill Family"), household_role))
    _, pat = create_patient(household_id=hh["id"])
    appt = create_appointment(pat["id"], scheduled_start="2026-07-01T09:00:00Z",
                              scheduled_end="2026-07-01T10:00:00Z")
    appointment_check_in(appt["id"])
    appointment_begin_exam(appt["id"])
    lo = create_resulted_lab_order(appt["id"], fee_cents=fee_cents)
    appointment_complete(appt["id"])
    hh_now = get_success_data(api_client.get_household(hh["id"], PRACTICE_MANAGER))
    return {
        "household": hh_now,
        "patient": pat,
        "appointment": appt,
        "lab_order": lo,
        "household_version": hh_now["version"],
    }


# ─── Tier 9: Boarding lifecycle ───────────────────────────────────────────────

def reserve_boarding(patient_id, kennel_id,
                     check_in_date="2026-07-01T00:00:00Z",
                     check_out_date="2026-07-03T00:00:00Z",
                     nightly_rate_cents=5000):
    return get_success_data(api_client.create_boarding_stay(
        create_boarding_stay_payload(patient_id, kennel_id,
                                     check_in_date=check_in_date,
                                     check_out_date=check_out_date,
                                     nightly_rate_cents=nightly_rate_cents),
        RECEPTIONIST))
