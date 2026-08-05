"""Isolated business-rule guards (membership, credits, refills-remaining)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_patient_payload, create_membership_plan_payload, create_membership_payload,
    create_draw_station_payload, create_lab_draw_appointment_payload,
    create_refill_order_payload,
    setup_active_plan, setup_plan_with_prescription, create_refill, get_prescription,
)

ADMIN = TEST_USERS["clinic_admin_headers"]


def test_activate_plan_with_trial_membership_rejected(api):
    """PRD §3.5: "the patient's membership must have `subscription_status` of `ACTIVE`,
    or the activation fails with `ERR_MEMBERSHIP_NOT_ACTIVE`".

    Design: Corner/validations/activate_plan_with_trial_membership_returns_membership_not_active
    """
    ctx = setup_active_plan(activate_membership=False, activate_plan=False)
    validate_error(
        api.activate_treatment_plan(ctx["plan_id"], ctx["clinician_headers"]),
        ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE, 409,
    )


def test_refill_create_delinquent_membership_rejected(api):
    """PRD §3.6: "then the membership's `payment_status` must be `CURRENT`, or the
    request is rejected with `ERR_MEMBERSHIP_DELINQUENT`."

    Design: Corner/validations/refill_create_delinquent_membership_returns_delinquent
    """
    ctx = setup_plan_with_prescription()
    get_success_data(api.record_payment(ctx["membership_id"], {"outcome": "FAILED"}, ADMIN))
    rx_version = get_prescription(ctx["rx_id"])["version"]
    payload = create_refill_order_payload(
        ctx["rx_id"], ctx["membership_id"], ctx["patient_id"], rx_version
    )
    validate_error(api.create_refill_order(payload, ADMIN), ApiErrorId.ERR_MEMBERSHIP_DELINQUENT, 402)


def test_book_lab_draw_with_zero_credits_rejected(api):
    """PRD §3.4: "the membership backing the patient must have at least one lab-draw
    credit remaining; a booking that would drive `lab_draw_credits_remaining` below
    zero is rejected with `ERR_INSUFFICIENT_LAB_DRAW_CREDITS`."

    Design: Corner/validations/book_lab_draw_with_zero_credits_returns_insufficient
    """
    patient = validate_success(api.create_patient(create_patient_payload(), ADMIN), 201)
    plan = validate_success(
        api.create_membership_plan(create_membership_plan_payload(tier="CORE", included_lab_draw_credits=1), ADMIN), 201
    )
    membership = validate_success(
        api.create_membership(create_membership_payload(patient["id"], plan["id"]), ADMIN), 201
    )
    get_success_data(api.activate_membership(membership["id"], ADMIN))
    station = validate_success(
        api.create_draw_station(create_draw_station_payload(name="St 5", concurrent_capacity=5), ADMIN), 201
    )
    # First booking consumes the single credit (credits now 0).
    get_success_data(api.create_lab_draw_appointment(
        create_lab_draw_appointment_payload(
            patient["id"], station["id"], "2026-05-05T09:00:00Z", "2026-05-05T09:30:00Z"
        ), ADMIN,
    ))
    # Second booking (non-overlapping time, so no capacity conflict) hits the credit floor.
    payload = create_lab_draw_appointment_payload(
        patient["id"], station["id"], "2026-05-05T11:00:00Z", "2026-05-05T11:30:00Z"
    )
    validate_error(
        api.create_lab_draw_appointment(payload, ADMIN),
        ApiErrorId.ERR_INSUFFICIENT_LAB_DRAW_CREDITS, 402,
    )


def test_dispense_exhausted_prescription_returns_no_refills_remaining(api):
    """PRD §3.6: "the prescription must have at least one refill remaining, or it fails
    with `ERR_NO_REFILLS_REMAINING` — an `EXHAUSTED` prescription reaches and fails
    this last check."
    PRD §3.6: "if that decrement drives `refills_remaining` to zero — moves the
    prescription to `EXHAUSTED`."

    Design: Corner/validations/dispense_exhausted_prescription_returns_no_refills_remaining
    """
    ctx = setup_plan_with_prescription(rx_overrides={"refills_authorized": 1})
    refill1 = create_refill(ctx)
    refill2 = create_refill(ctx)
    ph = ctx["pharmacist_headers"]
    get_success_data(api.dispense_refill_order(refill1["id"], {"dispensed_quantity_units": 8}, ph))
    assert get_prescription(ctx["rx_id"])["status"] == "EXHAUSTED"
    validate_error(
        api.dispense_refill_order(refill2["id"], {"dispensed_quantity_units": 8}, ph),
        ApiErrorId.ERR_NO_REFILLS_REMAINING, 409,
    )
    assert get_prescription(ctx["rx_id"])["status"] == "EXHAUSTED"
