"""Clinic appointments (room double-booking, check-in/no-show timing),
the COMPLETED VET_EXAM prescription gateway, and prescription-diet sale gating."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_clinic_appointment_payload, create_prescription_payload,
    create_product_sale_payload,
    make_store, make_product, make_customer, make_lot,
    make_completed_vet_exam, set_clock,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
VET = TEST_USERS["clinic_vet_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / clinic room half-open overlap
# ---------------------------------------------------------------------------
def test_clinic_room_half_open_overlap_rejected(api):
    """PRD §3.7: "within the same store and `room`, no existing appointment whose
    own `status` is `BOOKED` or `CHECKED_IN` may have a half-open time interval
    `[start_at, end_at)` that overlaps the new one; a violation is rejected with
    `ERR_ROOM_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/clinic_room_half_open_overlap_rejected
    """
    store = make_store()
    customer = make_customer(store["id"])
    validate_success(
        api.create_clinic_appointment(
            create_clinic_appointment_payload(
                store["id"], customer["id"], service_type="GROOMING", room="R1",
                start_at="2026-01-05T09:00:00Z", end_at="2026-01-05T10:00:00Z",
                fee_cents=5000,
            ), VET,
        ), 201,
    )
    # 09:30–10:30 overlaps the existing 09:00–10:00 in the same room.
    res = api.create_clinic_appointment(
        create_clinic_appointment_payload(
            store["id"], customer["id"], service_type="VACCINE", room="R1",
            start_at="2026-01-05T09:30:00Z", end_at="2026-01-05T10:30:00Z",
            fee_cents=6000,
        ), VET,
    )
    validate_error(res, ApiErrorId.ERR_ROOM_DOUBLE_BOOKED)


def test_clinic_room_touching_intervals_allowed(api):
    """PRD §3.7: "Because the interval is half-open, two appointments that merely
    touch — one ending exactly when the next begins — do not overlap and are both
    allowed."

    Design: Difficulty/resource_temporal_overlap/clinic_room_half_open_overlap_rejected
    """
    store = make_store()
    customer = make_customer(store["id"])
    validate_success(
        api.create_clinic_appointment(
            create_clinic_appointment_payload(
                store["id"], customer["id"], service_type="GROOMING", room="R1",
                start_at="2026-01-05T09:00:00Z", end_at="2026-01-05T10:00:00Z",
                fee_cents=5000,
            ), VET,
        ), 201,
    )
    # 10:00–11:00 starts exactly when the prior ends: touching, not overlapping.
    res = api.create_clinic_appointment(
        create_clinic_appointment_payload(
            store["id"], customer["id"], service_type="VACCINE", room="R1",
            start_at="2026-01-05T10:00:00Z", end_at="2026-01-05T11:00:00Z",
            fee_cents=6000,
        ), VET,
    )
    appt = validate_success(res, 201)
    assert appt["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / prescription requires VET_EXAM
# ---------------------------------------------------------------------------
def test_prescription_issue_requires_completed_vet_exam(api):
    """PRD §3.8: "The referenced `issued_by_appointment_id` must be a `COMPLETED`
    appointment whose `service_type` is `VET_EXAM` and whose customer is the same
    as the prescription's `customer_id`; otherwise issuance is rejected with
    `ERR_APPOINTMENT_NOT_ELIGIBLE`. A new prescription is `ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/prescription_issue_requires_completed_vet_exam
    """
    store = make_store()
    product = make_product(
        category="MEDICATION", unit_price_cents=4000, is_prescription_diet=True
    )
    customer = make_customer(store["id"])
    appt = make_completed_vet_exam(store["id"], customer["id"], fee_cents=8000)
    res = api.create_prescription(
        create_prescription_payload(
            customer["id"], product["id"], appt["id"],
            max_units_per_order=2, expires_at="2026-12-31T00:00:00Z",
        ), VET,
    )
    rx = validate_success(res, 201)
    assert rx["status"] == "ACTIVE"
    assert rx["issued_by_appointment_id"] == appt["id"]


def test_prescription_issue_from_booked_appointment_not_eligible(api):
    """PRD §3.8: "The referenced `issued_by_appointment_id` must be a `COMPLETED`
    appointment whose `service_type` is `VET_EXAM` and whose customer is the same
    as the prescription's `customer_id`; otherwise issuance is rejected with
    `ERR_APPOINTMENT_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/prescription_issue_requires_completed_vet_exam
    """
    store = make_store()
    product = make_product(
        category="MEDICATION", unit_price_cents=4000, is_prescription_diet=True
    )
    customer = make_customer(store["id"])
    # A still-BOOKED VET_EXAM is not COMPLETED → not eligible.
    appt = validate_success(
        api.create_clinic_appointment(
            create_clinic_appointment_payload(
                store["id"], customer["id"], service_type="VET_EXAM", room="R1",
                start_at="2026-01-05T09:00:00Z", end_at="2026-01-05T10:00:00Z",
                fee_cents=8000,
            ), VET,
        ), 201,
    )
    res = api.create_prescription(
        create_prescription_payload(
            customer["id"], product["id"], appt["id"],
            max_units_per_order=2, expires_at="2026-12-31T00:00:00Z",
        ), VET,
    )
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_NOT_ELIGIBLE)


# ---------------------------------------------------------------------------
# Corner: state_machines / appointment timing preconditions
# ---------------------------------------------------------------------------
def test_checkin_before_start_rejected(api):
    """PRD §3.7: "A `ClinicVet` checks in a booked appointment, advancing it from
    `BOOKED` to `CHECKED_IN`, permitted only when the appointment is `BOOKED` ...
    and only once the logical clock has reached at least `start_at` (otherwise
    `ERR_APPOINTMENT_NOT_STARTED`)".

    Design: Corner/state_machines/checkin_before_start_rejected
    """
    store = make_store()
    customer = make_customer(store["id"])
    appt = validate_success(
        api.create_clinic_appointment(
            create_clinic_appointment_payload(
                store["id"], customer["id"], service_type="VACCINE", room="R1",
                start_at="2026-01-05T09:00:00Z", end_at="2026-01-05T10:00:00Z",
                fee_cents=4000,
            ), VET,
        ), 201,
    )
    # Clock at default 2026-01-01, before start_at.
    res = api.check_in_appointment(appt["id"], VET)
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_NOT_STARTED)


def test_no_show_before_end_rejected(api):
    """PRD §3.7: "Or it may be marked a no-show, moving it from `BOOKED` to
    `NO_SHOW`, permitted only from `BOOKED` ... and only once the logical clock
    has reached at least `end_at` (otherwise `ERR_APPOINTMENT_NOT_ENDED`)".

    Design: Corner/state_machines/no_show_before_end_rejected
    """
    store = make_store()
    customer = make_customer(store["id"])
    appt = validate_success(
        api.create_clinic_appointment(
            create_clinic_appointment_payload(
                store["id"], customer["id"], service_type="VACCINE", room="R1",
                start_at="2026-01-05T09:00:00Z", end_at="2026-01-05T10:00:00Z",
                fee_cents=4000,
            ), VET,
        ), 201,
    )
    set_clock("2026-01-05T09:30:00Z")  # after start, before end
    res = api.no_show_appointment(appt["id"], VET)
    validate_error(res, ApiErrorId.ERR_APPOINTMENT_NOT_ENDED)


# ---------------------------------------------------------------------------
# Corner: validations / appointment end <= start invalid field
# ---------------------------------------------------------------------------
def test_invalid_field_value_end_before_start_appointment(api):
    """PRD §3.7: "a `start_at` (inclusive) and an `end_at` (exclusive, and
    required to be strictly after `start_at`)".
    PRD §2.6: "This includes ... an `end_at` that is not strictly after
    `start_at`".

    Design: Corner/validations/invalid_field_value_end_before_start_appointment
    """
    store = make_store()
    customer = make_customer(store["id"])
    res = api.create_clinic_appointment(
        create_clinic_appointment_payload(
            store["id"], customer["id"], service_type="GROOMING", room="R1",
            start_at="2026-01-05T10:00:00Z", end_at="2026-01-05T09:00:00Z",
            fee_cents=5000,
        ), VET,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_FIELD_VALUE)


# ---------------------------------------------------------------------------
# Corner: validations / prescription-diet sale without prescription
# ---------------------------------------------------------------------------
def test_prescription_diet_sale_without_active_prescription_rejected(api):
    """PRD §3.8: "When a point-of-sale product sale targets a product whose
    `is_prescription_diet` is true, the sale requires that the buying customer
    hold a prescription for that exact customer-and-product pair whose `status`
    is `ACTIVE`, whose `expires_at` is strictly after the current logical clock,
    and whose `max_units_per_order` is at least the quantity being sold. If no
    such prescription exists, or the requested quantity exceeds
    `max_units_per_order`, the sale is rejected with `ERR_PRESCRIPTION_REQUIRED`."

    Design: Corner/validations/prescription_diet_sale_without_active_prescription_rejected
    """
    store = make_store()
    product = make_product(
        category="MEDICATION", unit_price_cents=4000, is_prescription_diet=True
    )
    make_lot(store["id"], product["id"], quantity_on_hand=10)
    customer = make_customer(store["id"])
    res = api.create_product_sale(
        create_product_sale_payload(
            store["id"], product["id"], customer["id"], quantity=1
        ), CLERK,
    )
    validate_error(res, ApiErrorId.ERR_PRESCRIPTION_REQUIRED)
