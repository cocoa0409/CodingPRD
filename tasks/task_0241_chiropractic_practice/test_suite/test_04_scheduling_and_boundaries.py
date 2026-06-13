"""Scheduling-safety checks (provider/room availability, room type, half-open
provider overlap, room buffer), cap boundary precision, the dismissal-strike
boundary, and the priority-ordered conflict pairs.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_provider_headers,
    create_appointment_payload,
    setup_base_practice,
    create_provider,
    create_room,
    create_cash_patient,
    create_insurance_patient,
    add_policy,
    book_appointment,
    accrue_strikes,
    setup_dismissed_patient,
    setup_discontinued_plan_exhausted_policy,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]
BILLING = TEST_USERS["billing_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Difficulty: resource_temporal_overlap / provider_half_open_overlap_adjacency_allowed
# ===========================================================================
def test_provider_adjacent_booking_allowed(api):
    """PRD §3.6: "two appointments that merely abut, where one ends exactly when
    the next begins, do not conflict".

    A 16:15 start (== prior 16:00+15) on the same provider in a different room is
    allowed.

    Design: Difficulty/resource_temporal_overlap/provider_half_open_overlap_adjacency_allowed
    """
    fee = setup_base_practice()  # provider + room R1 + fee + clock
    prov_id = fee["provider"]["id"]
    r1 = fee["room"]["id"]
    r2 = create_room(name="R2", room_type="ADJUSTMENT", turnover_buffer_minutes=0)["id"]
    patient = create_cash_patient("Adj Al")
    pid = patient["id"]
    book_appointment(pid, prov_id, r1, scheduled_start="2026-03-10T16:00:00Z", duration_minutes=15)

    adjacent = validate_success(
        api.book_appointment(
            pid, create_appointment_payload(prov_id, r2, scheduled_start="2026-03-10T16:15:00Z", duration_minutes=15),
            FRONTDESK,
        ),
        201,
    )
    assert adjacent["attendance_status"] == "BOOKED"


def test_provider_overlap_rejected(api):
    """PRD §3.6: "the new appointment's half-open interval from its start up to
    (but not including) its end must not intersect any `BOOKED` or `CHECKED_IN`
    appointment for the same provider ... a true overlap is rejected with
    `ERR_PROVIDER_DOUBLE_BOOKED`."

    A 16:10 start lies inside [16:00,16:15) on the same provider.

    Design: Difficulty/resource_temporal_overlap/provider_half_open_overlap_adjacency_allowed
    """
    fee = setup_base_practice()
    prov_id = fee["provider"]["id"]
    r1 = fee["room"]["id"]
    r2 = create_room(name="R2", room_type="ADJUSTMENT", turnover_buffer_minutes=0)["id"]
    patient = create_cash_patient("Adj Ada")
    pid = patient["id"]
    book_appointment(pid, prov_id, r1, scheduled_start="2026-03-10T16:00:00Z", duration_minutes=15)

    res = api.book_appointment(
        pid, create_appointment_payload(prov_id, r2, scheduled_start="2026-03-10T16:10:00Z", duration_minutes=15),
        FRONTDESK,
    )
    validate_error(res, "ERR_PROVIDER_DOUBLE_BOOKED")


# ===========================================================================
# Difficulty: resource_temporal_overlap / room_buffer_closed_interval_adjacency_insufficient
# ===========================================================================
def test_room_buffer_adjacency_rejected(api):
    """PRD §3.6: "The room must respect its turnover buffer: the new appointment's
    start must be at or after the prior room appointment's end plus that room's
    `turnover_buffer_minutes`, so that a non-zero buffer makes mere adjacency
    insufficient; a start earlier than that is rejected with
    `ERR_ROOM_BUFFER_CONFLICT`."

    Room buffer 10m: a 16:15 start (== prior end) is inside the buffer -> rejected.

    Design: Difficulty/resource_temporal_overlap/room_buffer_closed_interval_adjacency_insufficient
    """
    fee = setup_base_practice(turnover_buffer_minutes=10)
    room_id = fee["room"]["id"]
    p1 = fee["provider"]["id"]
    p2 = create_provider(full_name="Dr Lin", npi="1234567891")["id"]
    patient = create_cash_patient("Buf Bob")
    pid = patient["id"]
    book_appointment(pid, p1, room_id, scheduled_start="2026-03-10T16:00:00Z", duration_minutes=15)

    res = api.book_appointment(
        pid, create_appointment_payload(p2, room_id, scheduled_start="2026-03-10T16:15:00Z", duration_minutes=15),
        FRONTDESK,
    )
    validate_error(res, "ERR_ROOM_BUFFER_CONFLICT")


def test_room_buffer_satisfied_allows_booking(api):
    """PRD §3.6: "the new appointment's start must be at or after the prior room
    appointment's end plus that room's `turnover_buffer_minutes`".

    Room buffer 10m: a 16:25 start (== prior end 16:15 + 10) is allowed.

    Design: Difficulty/resource_temporal_overlap/room_buffer_closed_interval_adjacency_insufficient
    """
    fee = setup_base_practice(turnover_buffer_minutes=10)
    room_id = fee["room"]["id"]
    p1 = fee["provider"]["id"]
    p2 = create_provider(full_name="Dr Lin", npi="1234567891")["id"]
    patient = create_cash_patient("Buf Bea")
    pid = patient["id"]
    book_appointment(pid, p1, room_id, scheduled_start="2026-03-10T16:00:00Z", duration_minutes=15)

    ok = validate_success(
        api.book_appointment(
            pid, create_appointment_payload(p2, room_id, scheduled_start="2026-03-10T16:25:00Z", duration_minutes=15),
            FRONTDESK,
        ),
        201,
    )
    assert ok["attendance_status"] == "BOOKED"


# ===========================================================================
# Difficulty: boundary_precision_check / cap_fills_last_slot_equal_allowed_but_plus_one_rejected
# ===========================================================================
def test_cap_boundary_fills_last_slot_then_rejects(api):
    """PRD §3.6: "If that projection is greater than the policy's
    `annual_visit_cap`, the booking is rejected with `ERR_VISIT_CAP_EXCEEDED`; a
    projection exactly equal to the cap is allowed, filling the final slot."

    cap=2: 1st booking reserved=1; 2nd booking (projection==2) allowed; 3rd
    booking (projection==3 > 2) rejected.

    Design: Difficulty/boundary_precision_check/cap_fills_last_slot_equal_allowed_but_plus_one_rejected
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Cap Carl")
    pid = patient["id"]
    prov_id, room_id = base["provider"]["id"], base["room"]["id"]
    policy = add_policy(pid, annual_visit_cap=2)

    appt1 = book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-10T09:00:00Z", insurance_policy_id=policy["id"])
    assert appt1["counts_against_cap"] is True

    second = validate_success(
        api.book_appointment(
            pid, create_appointment_payload(prov_id, room_id, scheduled_start="2026-03-11T09:00:00Z", insurance_policy_id=policy["id"]),
            FRONTDESK,
        ),
        201,
    )
    assert second["attendance_status"] == "BOOKED"
    policy_full = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert policy_full["visits_reserved"] == 2

    third = api.book_appointment(
        pid, create_appointment_payload(prov_id, room_id, scheduled_start="2026-03-12T09:00:00Z", insurance_policy_id=policy["id"]),
        FRONTDESK,
    )
    validate_error(third, "ERR_VISIT_CAP_EXCEEDED")


def test_cap_exactly_equal_to_cap_allowed(api):
    """PRD §3.6: "a projection exactly equal to the cap is allowed, filling the
    final slot."

    cap=1: the very first cap-counting booking projects to exactly 1 and is
    allowed.

    Design: Difficulty/boundary_precision_check/cap_fills_last_slot_equal_allowed_but_plus_one_rejected
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Cap Cleo")
    pid = patient["id"]
    policy = add_policy(pid, annual_visit_cap=1)
    appt = validate_success(
        api.book_appointment(
            pid, create_appointment_payload(base["provider"]["id"], base["room"]["id"], scheduled_start="2026-03-10T09:00:00Z", insurance_policy_id=policy["id"]),
            FRONTDESK,
        ),
        201,
    )
    assert appt["counts_against_cap"] is True
    refreshed = validate_success(api.get_policy_by_id(policy["id"], BILLING), 200)
    assert refreshed["visits_reserved"] == 1


# ===========================================================================
# Difficulty: boundary_precision_check / dismissal_threshold_strike4_active_strike5_dismissed
# ===========================================================================
def test_patient_active_at_four_strikes(api):
    """PRD §3.7: "when that count reaches the dismissal threshold of five, the
    patient is dismissed".

    After exactly 4 no-shows the patient is still ACTIVE (4 < 5).

    Design: Difficulty/boundary_precision_check/dismissal_threshold_strike4_active_strike5_dismissed
    """
    base = setup_base_practice()
    patient = create_cash_patient("Strike Sue")
    pid = patient["id"]
    accrue_strikes(pid, base["provider"]["id"], base["room"]["id"], 4, start_hour=9)
    at_four = validate_success(api.get_patient(pid, FRONTDESK), 200)
    assert at_four["no_show_strike_count"] == 4
    assert at_four["status"] == "ACTIVE"


def test_patient_dismissed_at_fifth_strike(api):
    """PRD §3.7: "when that count reaches the dismissal threshold of five, the
    patient is dismissed: `is_dismissed` becomes true and `status` moves to the
    terminal `DISMISSED`."

    The 5th no-show crosses the threshold and flips status to DISMISSED.

    Design: Difficulty/boundary_precision_check/dismissal_threshold_strike4_active_strike5_dismissed
    """
    base = setup_base_practice()
    patient = create_cash_patient("Strike Sal")
    pid = patient["id"]
    accrue_strikes(pid, base["provider"]["id"], base["room"]["id"], 5, start_hour=9)
    at_five = validate_success(api.get_patient(pid, FRONTDESK), 200)
    assert at_five["no_show_strike_count"] == 5
    assert at_five["status"] == "DISMISSED"
    assert at_five["is_dismissed"] is True


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / safety_dismissed_beats_temporal_double_book
# ===========================================================================
def test_dismissed_guard_precedes_double_book(api):
    """PRD §3.6: "the dismissed-patient (`ERR_PATIENT_DISMISSED`) guard, which
    precedes the booking-specific business rules."

    Booking for a DISMISSED patient into an overlapping provider slot returns the
    dismissed error, evaluated before the temporal double-book check.

    Design: Difficulty/priority_pair_validation_conflict/safety_dismissed_beats_temporal_double_book
    """
    ctx = setup_dismissed_patient("Dismiss Dan")
    pid = ctx["patient"]["id"]
    prov_id = ctx["provider"]["id"]
    room_id = ctx["room"]["id"]

    # Another patient holds the overlapping provider slot.
    other = create_cash_patient("Other Olive")
    book_appointment(other["id"], prov_id, room_id, scheduled_start="2026-03-10T17:00:00Z", duration_minutes=15)

    res = api.book_appointment(
        pid, create_appointment_payload(prov_id, room_id, scheduled_start="2026-03-10T17:00:00Z", duration_minutes=15),
        FRONTDESK,
    )
    validate_error(res, "ERR_PATIENT_DISMISSED")


def test_dismissed_guard_fires_even_with_free_slot(api):
    """PRD §3.6: "the dismissed-patient (`ERR_PATIENT_DISMISSED`) guard, which
    precedes the booking-specific business rules."

    With a completely free provider/room slot and no temporal conflict, a
    DISMISSED patient's booking is still rejected with `ERR_PATIENT_DISMISSED`,
    showing the safety guard is reached before any temporal-conflict check.

    Design: Difficulty/priority_pair_validation_conflict/safety_dismissed_beats_temporal_double_book
    """
    ctx = setup_dismissed_patient("Dismiss Deb")
    pid = ctx["patient"]["id"]
    res = api.book_appointment(
        pid,
        create_appointment_payload(
            ctx["provider"]["id"], ctx["room"]["id"], scheduled_start="2026-03-15T09:00:00Z", duration_minutes=15
        ),
        FRONTDESK,
    )
    validate_error(res, "ERR_PATIENT_DISMISSED")


# ===========================================================================
# Difficulty: cross_entity_state_dependency / completion_requires_signed_soap_appointment_to_soapnote
# ===========================================================================
def test_completion_requires_signed_soap(api):
    """PRD §3.7: "Completing an appointment requires it be `CHECKED_IN` and that a
    `SIGNED` SOAP note exist for it; a completion attempted without a signed note
    is rejected with `ERR_SOAP_NOTE_REQUIRED`."

    With only a DRAFT note, completion is rejected and the appointment stays
    CHECKED_IN.

    Design: Difficulty/cross_entity_state_dependency/completion_requires_signed_soap_appointment_to_soapnote
    """
    from test_helpers import create_soap_note_payload

    base = setup_base_practice()
    patient = create_cash_patient("Soap Sue")
    pid = patient["id"]
    prov_id, room_id = base["provider"]["id"], base["room"]["id"]
    appt = book_appointment(pid, prov_id, room_id, scheduled_start="2026-03-03T17:00:00Z")
    validate_success(api.check_in(pid, appt["id"], FRONTDESK), 200)
    # Draft note only — not signed.
    validate_success(
        api.create_soap_note(pid, appt["id"], create_soap_note_payload(prov_id), make_provider_headers(prov_id)), 201
    )
    res = api.complete_appointment(pid, appt["id"], make_provider_headers(prov_id))
    validate_error(res, "ERR_SOAP_NOTE_REQUIRED")
    after = validate_success(api.get_appointment(pid, appt["id"], FRONTDESK), 200)
    assert after["attendance_status"] == "CHECKED_IN"


def test_completion_succeeds_after_signing(api):
    """PRD §3.7: "a signed note is the prerequisite that unblocks completion."
    PRD §3.7: "On completion the appointment transitions `CHECKED_IN → ATTENDED`."

    Design: Difficulty/cross_entity_state_dependency/completion_requires_signed_soap_appointment_to_soapnote
    """
    from test_helpers import create_attended_appointment

    base = setup_base_practice()
    patient = create_cash_patient("Soap Sam")
    appt = create_attended_appointment(
        patient["id"], base["provider"]["id"], base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"
    )
    assert appt["attendance_status"] == "ATTENDED"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / booking_requires_active_patient_appointment_to_patient
# ===========================================================================
def test_booking_for_dismissed_patient_rejected(api):
    """PRD §3.2: "A `DISMISSED` patient may no longer be the subject of a booking,
    series generation, exam, or plan operation; such attempts are rejected with
    `ERR_PATIENT_DISMISSED`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_active_patient_appointment_to_patient
    """
    ctx = setup_dismissed_patient("Dismiss Dot")
    pid = ctx["patient"]["id"]
    res = api.book_appointment(
        pid,
        create_appointment_payload(ctx["provider"]["id"], ctx["room"]["id"], scheduled_start="2026-03-20T17:00:00Z"),
        FRONTDESK,
    )
    validate_error(res, "ERR_PATIENT_DISMISSED")


def test_dismissed_patient_is_terminal(api):
    """PRD §3.2: "the patient's `status` moves to the terminal `DISMISSED`."

    The dismissed patient reads back DISMISSED, confirming the booking guard's
    precondition.

    Design: Difficulty/cross_entity_state_dependency/booking_requires_active_patient_appointment_to_patient
    """
    ctx = setup_dismissed_patient("Dismiss Della")
    refreshed = validate_success(api.get_patient(ctx["patient"]["id"], FRONTDESK), 200)
    assert refreshed["status"] == "DISMISSED"


# ===========================================================================
# Corner: validations / suspended_provider_unavailable
# ===========================================================================
def test_suspended_provider_unavailable(api):
    """PRD §3.6: "the assigned provider must be `ACTIVE` (not `SUSPENDED`) and the
    assigned room must be `OPEN` (not `CLOSED`), failing with
    `ERR_RESOURCE_UNAVAILABLE`."

    Design: Corner/validations/suspended_provider_unavailable
    """
    base = setup_base_practice()
    prov_id = base["provider"]["id"]
    validate_success(api.suspend_provider(prov_id, ADMIN), 200)
    patient = create_cash_patient("Susp Sal")
    res = api.book_appointment(
        patient["id"],
        create_appointment_payload(prov_id, base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"),
        FRONTDESK,
    )
    validate_error(res, "ERR_RESOURCE_UNAVAILABLE")


# ===========================================================================
# Corner: validations / closed_room_unavailable
# ===========================================================================
def test_closed_room_unavailable(api):
    """PRD §3.1: "a room may later be closed, after which new bookings and series
    against it are rejected with `ERR_RESOURCE_UNAVAILABLE`".

    Design: Corner/validations/closed_room_unavailable
    """
    base = setup_base_practice()
    room_id = base["room"]["id"]
    closed = validate_success(api.close_room(room_id, ADMIN), 200)
    assert closed["status"] == "CLOSED"
    patient = create_cash_patient("Closed Cleo")
    res = api.book_appointment(
        patient["id"],
        create_appointment_payload(base["provider"]["id"], room_id, scheduled_start="2026-03-03T17:00:00Z"),
        FRONTDESK,
    )
    validate_error(res, "ERR_RESOURCE_UNAVAILABLE")


# ===========================================================================
# Corner: validations / xray_into_non_imaging_room_type_mismatch
# ===========================================================================
def test_xray_into_adjustment_room_type_mismatch(api):
    """PRD §3.6: "An `X_RAY` visit must be booked into a room whose `room_type` is
    `IMAGING`, failing with `ERR_ROOM_TYPE_MISMATCH`."

    Design: Corner/validations/xray_into_non_imaging_room_type_mismatch
    """
    base = setup_base_practice(visit_type="X_RAY", cash_rate_cents=20000)
    patient = create_cash_patient("Xray Xena")
    res = api.book_appointment(
        patient["id"],
        create_appointment_payload(
            base["provider"]["id"], base["room"]["id"], visit_type="X_RAY",
            scheduled_start="2026-03-03T17:00:00Z", duration_minutes=20,
        ),
        FRONTDESK,
    )
    validate_error(res, "ERR_ROOM_TYPE_MISMATCH")


# ===========================================================================
# Corner: validations / insurance_patient_without_policy_required
# ===========================================================================
def test_insurance_patient_without_policy_rejected(api):
    """PRD §3.6: "For an insurance patient, the booking must name an
    `insurance_policy_id` belonging to that patient and `ACTIVE`, failing with
    `ERR_POLICY_REQUIRED`."

    Design: Corner/validations/insurance_patient_without_policy_required
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Pol Polly")
    res = api.book_appointment(
        patient["id"],
        create_appointment_payload(base["provider"]["id"], base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z"),
        FRONTDESK,
    )
    validate_error(res, "ERR_POLICY_REQUIRED")


# ===========================================================================
# Corner: validations / terminated_policy_booking_rejected
# ===========================================================================
def test_terminated_policy_booking_rejected(api):
    """PRD §3.6: "For an insurance patient, the booking must name an
    `insurance_policy_id` belonging to that patient and `ACTIVE`, failing with
    `ERR_POLICY_REQUIRED`."
    PRD §3.2: "a terminated policy covers no new visits".

    A TERMINATED policy is not ACTIVE, so the booking fails ERR_POLICY_REQUIRED.

    Design: Corner/validations/terminated_policy_booking_rejected
    """
    base = setup_base_practice()
    patient = create_insurance_patient("Term Tess")
    pid = patient["id"]
    policy = add_policy(pid, annual_visit_cap=10)
    terminated = validate_success(api.terminate_policy(pid, policy["id"], BILLING), 200)
    assert terminated["status"] == "TERMINATED"
    res = api.book_appointment(
        pid,
        create_appointment_payload(base["provider"]["id"], base["room"]["id"], scheduled_start="2026-03-03T17:00:00Z", insurance_policy_id=policy["id"]),
        FRONTDESK,
    )
    validate_error(res, "ERR_POLICY_REQUIRED")
