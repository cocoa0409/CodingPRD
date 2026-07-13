"""Eye exams: the store's buffered half-open chair arithmetic, and the prescription
an exam produces."""

from test_helpers import (
    ApiErrorId,
    assert_exam_appointment,
    create_exam_appointment_payload,
    make_customer_headers,
    new_customer,
    new_exam_appointment,
    new_prescription,
    new_store,
    read_exam_appointment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import LOW_POWER_RX, STORE


# ═════════════════════════════════════════════════════════════════════════════
# Interval semantics A — half-open [start, end) plus a TRAILING store buffer
# ═════════════════════════════════════════════════════════════════════════════

def test_exam_inside_the_trailing_buffer_collides_at_a_one_chair_store(api):
    """PRD §2.10: "The consequence is worth stating plainly: two back-to-back exams
    separated by a gap of strictly less than `buffer_minutes` collide, and two exams
    separated by a gap of exactly `buffer_minutes` do **not** collide."
    PRD §2.10: "A store tolerates collisions up to its capacity; a booking is refused
    with `ERR_EXAM_SLOT_CONFLICT` only when the number of colliding appointments
    (counting both `BOOKED` and `COMPLETED` ones) is already greater than or equal to
    `exam_chairs`."

    A 10:00–10:30 exam at a 1-chair store with a 10-minute buffer occupies
    [10:00, 10:40). A 10:35 start leaves a 5-minute gap — strictly less than the
    buffer — so it collides.

    Design: Difficulty/resource_temporal_overlap/exam_half_open_interval_with_trailing_buffer_on_store
    """
    store = new_store(name="SoHo", exam_chairs=1, buffer_minutes=10, status="OPEN")
    customer = new_customer(full_name="Eve Xam", email="eve@example.com")
    new_exam_appointment(
        customer["id"], store["id"], "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z"
    )

    resp = api.create_exam_appointment(
        create_exam_appointment_payload(
            customer["id"],
            store["id"],
            "2026-06-01T10:35:00Z",
            "2026-06-01T11:05:00Z",
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EXAM_SLOT_CONFLICT.value)


def test_exam_exactly_one_buffer_after_the_previous_one_is_accepted(api):
    """PRD §2.10: "An exam occupies the span from `start_at` inclusive to `end_at`
    exclusive, and every store appends a turnover buffer of `buffer_minutes`
    **after** the interval, extending it."
    PRD §2.10: "The consequence is worth stating plainly: two back-to-back exams
    separated by a gap of strictly less than `buffer_minutes` collide, and two exams
    separated by a gap of exactly `buffer_minutes` do **not** collide."

    A 10:40 start is exactly one buffer after the 10:30 end, so the half-open
    buffered spans merely touch and are disjoint — the exact opposite of the closed
    kit-window rule.

    Design: Difficulty/resource_temporal_overlap/exam_half_open_interval_with_trailing_buffer_on_store
    """
    store = new_store(name="SoHo", exam_chairs=1, buffer_minutes=10, status="OPEN")
    customer = new_customer(full_name="Eve Xam", email="eve@example.com")
    first = new_exam_appointment(
        customer["id"], store["id"], "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z"
    )

    colliding = api.create_exam_appointment(
        create_exam_appointment_payload(
            customer["id"], store["id"], "2026-06-01T10:35:00Z", "2026-06-01T11:05:00Z"
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(colliding, ApiErrorId.ERR_EXAM_SLOT_CONFLICT.value)

    resp = api.create_exam_appointment(
        create_exam_appointment_payload(
            customer["id"], store["id"], "2026-06-01T10:40:00Z", "2026-06-01T11:10:00Z"
        ),
        make_customer_headers(customer["id"]),
    )
    second = validate_success(resp, 201)

    assert_exam_appointment(second)
    assert second["status"] == "BOOKED"
    assert second["resulting_prescription_id"] is None

    listed = api.list_exam_appointments(STORE, params={"store_id": store["id"]})
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 2, "the 10:35 booking never landed; the 10:40 one did"
    assert {r["id"] for r in rows} == {first["id"], second["id"]}


# ═════════════════════════════════════════════════════════════════════════════
# Exam completion
# ═════════════════════════════════════════════════════════════════════════════

def test_completing_an_exam_links_the_prescription_it_produced(api):
    """PRD §3.3: "A `StoreAssociate` closes the exam by completing it, which advances
    the appointment `BOOKED → COMPLETED` and links the prescription the exam
    produced: the payload carries a `prescription_id`, which is written to
    `resulting_prescription_id`, and the appointment's `version` increments."
    PRD §3.3: "Appointments may be read individually and listed with filters on
    `customer_id`, `store_id`, `resulting_prescription_id`, and `status`."

    Design: Corner/state_machines/exam_completion_links_the_resulting_prescription
    """
    store = new_store(name="Flatiron", exam_chairs=2)
    customer = new_customer(full_name="Ex Amme", email="exam@example.com")
    rx = new_prescription(customer["id"], **LOW_POWER_RX)
    appointment = new_exam_appointment(
        customer["id"], store["id"], "2026-06-01T09:00:00Z", "2026-06-01T09:30:00Z"
    )

    resp = api.complete_exam_appointment(
        appointment["id"], {"prescription_id": rx["id"]}, STORE
    )
    data = validate_success(resp, 200)

    assert data["status"] == "COMPLETED"
    assert data["resulting_prescription_id"] == rx["id"]
    assert read_exam_appointment(appointment["id"])["status"] == "COMPLETED"

    listed = api.list_exam_appointments(
        STORE, params={"resulting_prescription_id": rx["id"]}
    )
    rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == appointment["id"]


def test_booking_an_exam_at_an_unknown_store_is_a_store_not_found(api):
    """PRD §2.9: "**Body reference existence.** Every resource id referenced in the
    request body exists; the codes are `ERR_CUSTOMER_NOT_FOUND`,
    `ERR_FRAME_NOT_FOUND`, `ERR_LENS_OPTION_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`,
    `ERR_STORE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND` and
    `ERR_APPOINTMENT_NOT_FOUND`, all HTTP 404."

    The body-reference check sits above the chair-overlap arithmetic, so an unknown
    store never reaches the interval maths.

    Design: Corner/errors/booking_an_exam_at_an_unknown_store_returns_store_not_found
    """
    customer = new_customer(full_name="No Store", email="nostore@example.com")

    resp = api.create_exam_appointment(
        create_exam_appointment_payload(
            customer["id"],
            "22222222-2222-4222-8222-222222222222",
            "2026-06-01T10:00:00Z",
            "2026-06-01T10:30:00Z",
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STORE_NOT_FOUND.value)
