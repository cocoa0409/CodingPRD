"""Compensating invariants: refills_remaining and lab-draw credits conservation."""
from test_helpers import (
    validate_success, get_success_data, TEST_USERS,
    create_patient, create_membership_plan, create_membership, create_draw_station,
    setup_plan_with_prescription, create_refill, get_prescription, get_membership,
    create_lab_draw_appointment_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_dispense_decrements_refills_remaining(api):
    """PRD §3.6: "On dispense the system computes `final_charge_cents` from
    `dispensed_quantity_units`, decrements the prescription's `refills_remaining` by
    one, and — if that decrement drives `refills_remaining` to zero — moves the
    prescription to `EXHAUSTED`."

    Design: Difficulty/compensating_invariant/refill_reverse_conserves_refills_remaining
    """
    ctx = setup_plan_with_prescription(rx_overrides={"refills_authorized": 3})
    refill = create_refill(ctx)
    get_success_data(api.dispense_refill_order(refill["id"], {"dispensed_quantity_units": 8}, ctx["pharmacist_headers"]))
    assert get_prescription(ctx["rx_id"])["refills_remaining"] == 2


def test_reverse_restores_refills_remaining(api):
    """PRD §3.6: "A `Pharmacist` may reverse a dispensed order, moving it from
    `DISPENSED` to `REVERSED` (otherwise `ERR_INVALID_STATE`); reversal increments the
    prescription's `refills_remaining` by one as a compensating entry, and if the
    prescription was `EXHAUSTED` and now has a positive `refills_remaining`, it is
    restored to `ISSUED`."

    Design: Difficulty/compensating_invariant/refill_reverse_conserves_refills_remaining
    """
    ctx = setup_plan_with_prescription(rx_overrides={"refills_authorized": 3})
    refill = create_refill(ctx)
    get_success_data(api.dispense_refill_order(refill["id"], {"dispensed_quantity_units": 8}, ctx["pharmacist_headers"]))
    reversed_order = validate_success(api.reverse_refill_order(refill["id"], ctx["pharmacist_headers"]), 200)
    assert reversed_order["status"] == "REVERSED"
    rx = get_prescription(ctx["rx_id"])
    assert rx["refills_remaining"] == 3
    assert rx["status"] == "ISSUED"


def _booked_appointment(api):
    patient = create_patient()
    plan = create_membership_plan(included_lab_draw_credits=4)
    membership = create_membership(patient["id"], plan["id"], activate=True)
    station = create_draw_station(name="Station 2", concurrent_capacity=2)
    appt = get_success_data(api.create_lab_draw_appointment(
        create_lab_draw_appointment_payload(patient["id"], station["id"], "2026-05-04T10:00:00Z", "2026-05-04T10:30:00Z"), ADMIN
    ))
    return membership, appt


def test_booking_consumes_one_credit(api):
    """PRD §3.4: "A successful booking decrements the membership's
    `lab_draw_credits_remaining` by one."

    Design: Difficulty/compensating_invariant/labdraw_cancel_conserves_credits
    """
    membership, _ = _booked_appointment(api)
    assert get_membership(membership["id"])["lab_draw_credits_remaining"] == 3


def test_cancel_restores_lab_draw_credit(api):
    """PRD §3.4: "Cancellation of a scheduled appointment restores one credit,
    incrementing the membership's `lab_draw_credits_remaining` by one".

    Design: Difficulty/compensating_invariant/labdraw_cancel_conserves_credits
    """
    membership, appt = _booked_appointment(api)
    cancelled = validate_success(api.cancel_lab_draw_appointment(appt["id"], ADMIN), 200)
    assert cancelled["status"] == "CANCELLED"
    assert get_membership(membership["id"])["lab_draw_credits_remaining"] == 4
