"""Appointment booking rules: window boundaries, turnover-buffer overlap,
sedation buffer, cancelled-slot reuse, monthly scan cap, lifecycle order, and
coordinator ownership."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_appointment,
    create_appointment_payload,
    create_facility,
    get_success_data,
    make_facility_coordinator_headers,
    setup_bookable_day,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


def test_appointment_end_at_window_close_inclusive(api):
    """PRD §3.5: "The slot must sit inside the service window: `scheduled_start`
    no earlier than `first_patient_time`, and the appointment's effective end —
    `scheduled_start` plus `duration_minutes` plus a 15-minute sedation buffer
    when `sedation_required` is true — no later than `last_patient_time`, with
    the window close inclusive so an effective end exactly equal to
    `last_patient_time` is allowed; violations are `ERR_SLOT_OUTSIDE_WINDOW`."

    Design: Difficulty/boundary_precision_check/appointment_end_exactly_at_window_close_allowed
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])

    # 15:30 + 30 min = 16:00 == last_patient_time -> inclusive close allows it.
    payload = create_appointment_payload(
        day["id"], "P-EDGE", scheduled_start="15:30", duration_minutes=30
    )
    resp = api.create_appointment(payload, coord)
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED"
    assert data["scheduled_start"] == "15:30"


def test_appointment_end_one_minute_past_window_close_rejected(api):
    """PRD §3.5: "The slot must sit inside the service window: `scheduled_start`
    no earlier than `first_patient_time`, and the appointment's effective end —
    `scheduled_start` plus `duration_minutes` plus a 15-minute sedation buffer
    when `sedation_required` is true — no later than `last_patient_time`, with
    the window close inclusive so an effective end exactly equal to
    `last_patient_time` is allowed; violations are `ERR_SLOT_OUTSIDE_WINDOW`."

    Design: Difficulty/boundary_precision_check/appointment_end_exactly_at_window_close_allowed
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])

    # 15:31 + 30 min = 16:01 > 16:00 -> outside the window.
    payload = create_appointment_payload(
        day["id"], "P-OVER", scheduled_start="15:31", duration_minutes=30
    )
    resp = api.create_appointment(payload, coord)
    validate_error(resp, ApiErrorId.ERR_SLOT_OUTSIDE_WINDOW)


def test_turnover_buffer_blocks_start_inside_buffer(api):
    """PRD §3.5: "Collision uses half-open intervals with a 10-minute trailing
    turnover buffer on each appointment's effective end: a new appointment
    conflicts with an existing one when the new start is earlier than the
    existing appointment's effective end plus ten minutes and the existing
    appointment's start is earlier than the new appointment's effective end
    plus ten minutes. Any conflict is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_turnover_buffer_overlap_semantics
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])
    book_appointment(day["id"], bundle["facility"]["id"], "P-001", scheduled_start="09:00")

    # Existing effective end 09:30 + 10 min buffer = 09:40; 09:35 < 09:40 -> conflict.
    payload = create_appointment_payload(
        day["id"], "P-002", scheduled_start="09:35", duration_minutes=30
    )
    resp = api.create_appointment(payload, coord)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP)


def test_turnover_buffer_boundary_start_allowed(api):
    """PRD §3.5: "Collision uses half-open intervals with a 10-minute trailing
    turnover buffer on each appointment's effective end: a new appointment
    conflicts with an existing one when the new start is earlier than the
    existing appointment's effective end plus ten minutes and the existing
    appointment's start is earlier than the new appointment's effective end
    plus ten minutes. Any conflict is rejected with `ERR_SLOT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/appointment_turnover_buffer_overlap_semantics
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])
    book_appointment(day["id"], bundle["facility"]["id"], "P-001", scheduled_start="09:00")

    # 09:40 equals the buffered boundary exactly; 09:40 < 09:40 is false -> allowed.
    payload = create_appointment_payload(
        day["id"], "P-003", scheduled_start="09:40", duration_minutes=30
    )
    resp = api.create_appointment(payload, coord)
    data = validate_success(resp, 201)
    assert data["status"] == "REQUESTED"


def test_overlap_check_ignores_cancelled_appointments(api):
    """PRD §3.5: "The slot must also not collide with the day's existing
    appointments in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or `SCANNING`
    (appointments already `COMPLETED`, `CANCELLED`, or `NO_SHOW` do not block)."

    Design: Corner/calculations/overlap_check_ignores_cancelled_appointments
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])

    appt = book_appointment(day["id"], bundle["facility"]["id"], "P-001", scheduled_start="09:00")
    get_success_data(api.cancel_appointment(appt["id"], {"reason": "patient request"}, coord))

    payload = create_appointment_payload(
        day["id"], "P-002", scheduled_start="09:00", duration_minutes=30
    )
    resp = api.create_appointment(payload, coord)
    data = validate_success(resp, 201)
    assert data["scheduled_start"] == "09:00"


def test_sedation_buffer_extends_effective_end(api):
    """PRD §3.5: "The slot must sit inside the service window: `scheduled_start`
    no earlier than `first_patient_time`, and the appointment's effective end —
    `scheduled_start` plus `duration_minutes` plus a 15-minute sedation buffer
    when `sedation_required` is true — no later than `last_patient_time`, with
    the window close inclusive so an effective end exactly equal to
    `last_patient_time` is allowed; violations are `ERR_SLOT_OUTSIDE_WINDOW`."

    Design: Corner/calculations/sedation_buffer_extends_effective_end
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])

    # Unsedated 15:30 + 30 = 16:00 exactly at the inclusive close -> accepted.
    calm = book_appointment(
        day["id"], bundle["facility"]["id"], "P-CALM",
        scheduled_start="15:30", duration_minutes=30, sedation_required=False,
    )
    get_success_data(api.cancel_appointment(calm["id"], {}, coord))

    # Sedated 15:30 + 30 + 15 = 16:15 > 16:00 -> rejected.
    payload = create_appointment_payload(
        day["id"], "P-SED", scheduled_start="15:30", duration_minutes=30,
        sedation_required=True,
    )
    resp = api.create_appointment(payload, coord)
    validate_error(resp, ApiErrorId.ERR_SLOT_OUTSIDE_WINDOW)


def test_scan_cap_allows_capth_booking_then_rejects(api):
    """PRD §3.5: "Last of all — it is the fiscal gate on the §2.8 ladder, so all
    earlier checks fire first — the contract's `monthly_scan_cap` is enforced:
    counting every appointment on site days under the same contract whose
    `service_date` falls in the target calendar month and whose status is
    anything but `CANCELLED`, the booking is rejected with
    `ERR_SCAN_CAP_EXCEEDED` when that count has already reached the cap;
    booking the appointment that reaches the cap is allowed, and only the next
    one is refused."

    Design: Corner/calculations/scan_cap_allows_capth_booking_then_rejects
    """
    bundle = setup_bookable_day(
        billing_model="PER_SCAN", contract_overrides={"monthly_scan_cap": 2}
    )
    day = bundle["site_day"]
    coord = make_facility_coordinator_headers(bundle["facility"]["id"])

    r1 = api.create_appointment(
        create_appointment_payload(day["id"], "P-001", scheduled_start="09:00"), coord
    )
    validate_success(r1, 201)
    r2 = api.create_appointment(
        create_appointment_payload(day["id"], "P-002", scheduled_start="09:40"), coord
    )
    validate_success(r2, 201)

    # Count is now 2 >= cap 2 -> the next booking is refused.
    r3 = api.create_appointment(
        create_appointment_payload(day["id"], "P-003", scheduled_start="10:20"), coord
    )
    validate_error(r3, ApiErrorId.ERR_SCAN_CAP_EXCEEDED)


def test_double_confirm_appointment_returns_invalid_state(api):
    """PRD §3.5: "Every out-of-order transition answers `ERR_INVALID_STATE`."

    Design: Corner/state_machines/double_confirm_appointment_returns_invalid_state
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    appt = book_appointment(
        bundle["site_day"]["id"], bundle["facility"]["id"], "P-001"
    )
    get_success_data(api.confirm_appointment(appt["id"], OPS))

    resp = api.confirm_appointment(appt["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_coordinator_of_other_facility_cannot_book(api):
    """PRD §3.5: "A `FacilityCoordinator` books a `PatientAppointment` into one
    of their own facility's site days — if the acting coordinator's facility
    differs from the day's facility, the booking is rejected with
    `ERR_FACILITY_MISMATCH`."

    Design: Corner/rbac/coordinator_of_other_facility_cannot_book
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    facility_b = create_facility(name="Clinic B", address="2 B Ave")
    foreign_coord = make_facility_coordinator_headers(facility_b["id"])

    payload = create_appointment_payload(
        bundle["site_day"]["id"], "P-900", scheduled_start="09:00"
    )
    resp = api.create_appointment(payload, foreign_coord)
    validate_error(resp, ApiErrorId.ERR_FACILITY_MISMATCH)
