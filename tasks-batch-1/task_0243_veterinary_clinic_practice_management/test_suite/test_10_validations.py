"""Isolated validation rejections: future vaccine administration, controlled-substance
refill cooldown, no-refills-remaining, surgery invalid time range, and deposit-not-met.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_household, create_patient, create_operatory, create_prescription,
    create_estimate, present_estimate, create_appointment_in_exam,
    TEST_USERS,
)

RECEPTIONIST = TEST_USERS["receptionist_headers"]
VETERINARIAN = TEST_USERS["veterinarian_headers"]
PRACTICE_MANAGER = TEST_USERS["practice_manager_headers"]


def test_future_vaccine_administration_rejected(api):
    """PRD 3.4: "the `administered_at` time (ISO 8601 UTC, which must not be after the
    clock's current time, else `ERR_FUTURE_ADMINISTRATION`)".

    A vaccination dated 2099 (after now) is rejected.

    Design: Corner/validations/future_vaccine_administration_rejected
    """
    hh = create_household("Pi")
    _, pat = create_patient(household_id=hh["id"], name="FuturePet",
                            species="DOG", weight_kg=8)
    res = api.create_vaccination({
        "patient_id": pat["id"], "vaccine_code": "RABIES",
        "administered_at": "2099-01-01T10:00:00Z",
    }, VETERINARIAN)
    validate_error(res, "ERR_FUTURE_ADMINISTRATION", expected_status=422)


def test_controlled_refill_cooldown_rejected(api):
    """PRD 3.5: "If the drug is controlled, a cooldown applies: the time elapsed since
    `last_refill_at` must be at least 30 days, and a refill attempted strictly within 30
    days of the last one is refused with `ERR_CONTROLLED_COOLDOWN`."

    A second refill of a controlled Rx immediately after the first (well within 30 days)
    is rejected.

    Design: Corner/validations/controlled_refill_cooldown_rejected
    """
    hh = create_household("Rho")
    _, pat = create_patient(household_id=hh["id"], name="Rx Pet",
                            species="DOG", weight_kg=15)
    rx = create_prescription(pat["id"], refills_authorized=3, is_controlled=True,
                             drug_name="Phenobarbital")
    validate_success(api.refill_prescription(rx["id"], VETERINARIAN), 200)
    res = api.refill_prescription(rx["id"], VETERINARIAN)
    validate_error(res, "ERR_CONTROLLED_COOLDOWN", expected_status=422)


def test_no_refills_remaining_rejected(api):
    """PRD 3.5: "there must be refills available — the difference between
    `refills_authorized` and `refills_used` must be greater than zero, or the refill is
    refused with `ERR_NO_REFILLS_REMAINING`."

    A non-controlled Rx with zero authorized refills is ACTIVE but has no refills
    available, so the first refill attempt is rejected. (A prescription with one
    authorized refill would auto-advance to EXHAUSTED after its single dispense per
    PRD 3.5, so a second attempt there trips ERR_PRESCRIPTION_NOT_ACTIVE instead;
    zero-authorized is the only setup that uniquely exercises ERR_NO_REFILLS_REMAINING.)

    Design: Corner/validations/no_refills_remaining_rejected
    """
    hh = create_household("Sig")
    _, pat = create_patient(household_id=hh["id"], name="OnePet",
                            species="CAT", weight_kg=4)
    rx = create_prescription(pat["id"], refills_authorized=0, is_controlled=False,
                             drug_name="Amox")
    res = api.refill_prescription(rx["id"], VETERINARIAN)
    validate_error(res, "ERR_NO_REFILLS_REMAINING", expected_status=409)


def test_surgery_window_invalid_time_range_rejected(api):
    """PRD 3.8: "a `window_start` and `window_end` (ISO 8601 UTC, with the end strictly
    after the start, else `ERR_INVALID_TIME_RANGE`)".

    A surgery whose window_end equals window_start is rejected.

    Design: Corner/validations/surgery_window_invalid_time_range_rejected
    """
    operatory = create_operatory(cleanup_buffer_minutes=30, name="OR-T")
    hh = create_household("Tau")
    _, pat = create_patient(household_id=hh["id"], name="SurgPet",
                            species="DOG", weight_kg=10)
    est = create_estimate(pat["id"], line_items=[
        {"service_code": "S", "qty": 1, "unit_price_cents": 30000, "eligible_for_plan_discount": False}],
        deposit_required_cents=0)
    present_estimate(est["id"])
    from test_helpers import approve_estimate
    approve_estimate(est["id"])
    appt = create_appointment_in_exam(pat["id"],
                                      scheduled_start="2026-08-06T09:00:00Z",
                                      scheduled_end="2026-08-06T12:00:00Z")
    res = api.create_surgery({
        "appointment_id": appt["id"], "operatory_id": operatory["id"],
        "estimate_id": est["id"], "procedure_name": "Bad",
        "window_start": "2026-08-06T10:00:00Z",
        "window_end": "2026-08-06T10:00:00Z",
    }, VETERINARIAN)
    validate_error(res, "ERR_INVALID_TIME_RANGE", expected_status=400)


def test_deposit_not_met_on_approve_rejected(api):
    """PRD 3.6: "approval requires the estimate to be `PRESENTED` and requires that
    `deposit_posted_cents` be at least `deposit_required_cents`, otherwise the approval is
    refused with `ERR_DEPOSIT_NOT_MET`."

    A PRESENTED estimate (state precondition satisfied) with deposit_required 40000 and 0
    posted is rejected with ERR_DEPOSIT_NOT_MET on approve.

    Design: Corner/validations/deposit_not_met_covered_indirectly_distinct_from_state
    """
    hh = create_household("Ups")
    _, pat = create_patient(household_id=hh["id"], name="DepPet",
                            species="DOG", weight_kg=9)
    est = create_estimate(pat["id"], line_items=[
        {"service_code": "S", "qty": 1, "unit_price_cents": 40000, "eligible_for_plan_discount": False}],
        deposit_required_cents=40000)
    present_estimate(est["id"])
    res = api.transition_estimate(est["id"], {"action": "approve"}, RECEPTIONIST)
    validate_error(res, "ERR_DEPOSIT_NOT_MET", expected_status=402)
