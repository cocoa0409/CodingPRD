"""Styling appointments: reschedule cycle, validation precedence, and the two
overlap geometries (buffered specialist vs half-open customer).

Queue A (Difficulty): appointment_reschedule_cycle_returns_to_confirmed,
confirm_specialty_beats_specialist_overlap, specialist_buffered_overlap_rejected,
customer_halfopen_double_booking_rejected.
Queue B (Corner): complete-before-end.
"""
from datetime import datetime

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_customer_headers, make_fit_specialist_headers,
    register_customer, create_specialist,
    book_appointment, confirm_appointment,
)

SM = TEST_USERS["store_manager_headers"]


def _instant(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# appointment_reschedule_cycle_returns_to_confirmed (Queue A)
# ---------------------------------------------------------------------------
def _confirmed_general_appointment(api):
    customer = register_customer(api)
    specialist = create_specialist(api, specialties=["ADAPTIVE"])
    appt = book_appointment(api, customer["id"], specialist["id"],
                            "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z")
    confirm_appointment(api, appt["id"])
    return customer, specialist, appt


def test_reschedule_request_moves_confirmed_to_reschedule_requested(api):
    """PRD §3.5: "The customer requests a reschedule, moving `CONFIRMED` to
    `RESCHEDULE_REQUESTED`; this requires that the appointment currently be
    `CONFIRMED` and that the supplied `proposed_start_at` be earlier than the
    supplied `proposed_end_at`, and it stores those two proposed times."

    Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_returns_to_confirmed
    """
    customer, specialist, appt = _confirmed_general_appointment(api)
    resp = api.transition_appointment(
        appt["id"],
        {"action": "RESCHEDULE_REQUEST",
         "proposed_start_at": "2026-07-06T10:00:00Z",
         "proposed_end_at": "2026-07-06T11:00:00Z"},
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp)
    assert data["status"] == "RESCHEDULE_REQUESTED"


def test_reschedule_confirm_returns_to_confirmed_with_promoted_start(api):
    """PRD §3.5: "A specialist or store manager then confirms the reschedule, moving
    `RESCHEDULE_REQUESTED` back to `CONFIRMED`; this re-runs the specialist and
    customer overlap checks at the proposed interval (again yielding
    `ERR_SPECIALIST_UNAVAILABLE` or `ERR_CUSTOMER_DOUBLE_BOOKED` on a conflict), then
    promotes the proposal by setting `start_at` to `proposed_start_at` and `end_at`
    to `proposed_end_at` and clearing both proposed fields."

    Design: Difficulty/non_linear_state_machine/appointment_reschedule_cycle_returns_to_confirmed
    """
    customer, specialist, appt = _confirmed_general_appointment(api)
    api.transition_appointment(
        appt["id"],
        {"action": "RESCHEDULE_REQUEST",
         "proposed_start_at": "2026-07-06T10:00:00Z",
         "proposed_end_at": "2026-07-06T11:00:00Z"},
        make_customer_headers(customer["id"]),
    )
    resp = api.transition_appointment(appt["id"], {"action": "RESCHEDULE_CONFIRM"}, SM)
    data = validate_success(resp)
    assert data["status"] == "CONFIRMED"
    assert _instant(data["start_at"]) == _instant("2026-07-06T10:00:00Z")


# ---------------------------------------------------------------------------
# confirm_specialty_beats_specialist_overlap (Queue A)
# ---------------------------------------------------------------------------
def _dual_failure_confirm_scenario(api):
    """Specialist skilled only in PLUS_FORMAL (buffer 0) with a confirmed
    10:00-11:00; a second customer's REQUESTED 10:30-11:30 ADAPTIVE appointment
    that both mismatches specialty (pri 6) and overlaps the specialist (pri 8)."""
    cust_a = register_customer(api)
    cust_b = register_customer(api)
    specialist = create_specialist(api, specialties=["PLUS_FORMAL"], buffer_minutes=0)
    blocking = book_appointment(api, cust_a["id"], specialist["id"],
                                "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z",
                                topic="PLUS_FORMAL")
    confirm_appointment(api, blocking["id"])
    bad = book_appointment(api, cust_b["id"], specialist["id"],
                           "2026-07-05T10:30:00Z", "2026-07-05T11:30:00Z", topic="ADAPTIVE")
    return bad


def test_specialty_mismatch_precedes_specialist_overlap(api):
    """PRD §2.9: "when a single request could fail several checks, the checks are
    evaluated in a fixed priority order, and the first failure encountered determines
    the error returned."
    PRD §3.5: "the `topic` must be `GENERAL` or must appear in the specialist's
    `specialties`, else `ERR_SPECIALTY_MISMATCH`".

    Design: Difficulty/priority_pair_validation_conflict/confirm_specialty_beats_specialist_overlap
    """
    bad = _dual_failure_confirm_scenario(api)
    resp = api.transition_appointment(bad["id"], {"action": "CONFIRM"}, SM)
    validate_error(resp, ApiErrorId.ERR_SPECIALTY_MISMATCH.value)


def test_specialty_mismatch_leaves_appointment_requested(api):
    """PRD §2.9: "the checks are evaluated in a fixed priority order, and the first
    failure encountered determines the error returned."
    PRD §3.5: "Confirming an appointment moves it from `REQUESTED` to `CONFIRMED` and
    is where the scheduling constraints bite."

    Design: Difficulty/priority_pair_validation_conflict/confirm_specialty_beats_specialist_overlap
    """
    bad = _dual_failure_confirm_scenario(api)
    api.transition_appointment(bad["id"], {"action": "CONFIRM"}, SM)
    result = validate_success(api.get_appointment(bad["id"], SM))
    assert result["status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# specialist_buffered_overlap_rejected (Queue A)
# ---------------------------------------------------------------------------
def test_specialist_buffer_clearance_rejects_near_booking(api):
    """PRD §3.5: "The specialist is a buffered single-occupancy resource: a conflict
    exists if any other appointment on the same `specialist_id` that is currently
    `CONFIRMED` or `RESCHEDULE_REQUESTED` has its interval come within the
    specialist's `buffer_minutes` of this one — precisely, when this appointment's
    `start_at` minus the buffer is earlier than the other's `end_at`, and the other's
    `start_at` is earlier than this appointment's `end_at` plus the buffer."

    Design: Difficulty/resource_temporal_overlap/specialist_buffered_overlap_rejected
    """
    cust_a = register_customer(api)
    cust_b = register_customer(api)
    specialist = create_specialist(api, specialties=["ADAPTIVE"], buffer_minutes=15)
    first = book_appointment(api, cust_a["id"], specialist["id"],
                             "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z")
    confirm_appointment(api, first["id"])
    second = book_appointment(api, cust_b["id"], specialist["id"],
                              "2026-07-05T11:10:00Z", "2026-07-05T11:40:00Z")
    resp = api.transition_appointment(second["id"], {"action": "CONFIRM"}, SM)
    validate_error(resp, ApiErrorId.ERR_SPECIALIST_UNAVAILABLE.value)


def test_specialist_booking_beyond_buffer_confirms(api):
    """PRD §3.5: "The specialist is a buffered single-occupancy resource: a conflict
    exists if any other appointment on the same `specialist_id` that is currently
    `CONFIRMED` or `RESCHEDULE_REQUESTED` has its interval come within the
    specialist's `buffer_minutes` of this one — precisely, when this appointment's
    `start_at` minus the buffer is earlier than the other's `end_at`, and the other's
    `start_at` is earlier than this appointment's `end_at` plus the buffer."

    Design: Difficulty/resource_temporal_overlap/specialist_buffered_overlap_rejected
    """
    cust_a = register_customer(api)
    cust_b = register_customer(api)
    specialist = create_specialist(api, specialties=["ADAPTIVE"], buffer_minutes=15)
    first = book_appointment(api, cust_a["id"], specialist["id"],
                             "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z")
    confirm_appointment(api, first["id"])
    # 11:20 start clears the 15-minute buffer after the 11:00 end (11:20-15=11:05 >= 11:00).
    second = book_appointment(api, cust_b["id"], specialist["id"],
                              "2026-07-05T11:20:00Z", "2026-07-05T11:50:00Z")
    data = validate_success(api.transition_appointment(second["id"], {"action": "CONFIRM"}, SM))
    assert data["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# customer_halfopen_double_booking_rejected (Queue A)
# ---------------------------------------------------------------------------
def test_customer_overlapping_second_booking_rejected(api):
    """PRD §3.5: "The customer is an unbuffered resource compared on the raw
    half-open intervals: a conflict exists if any other appointment for the same
    `customer_id` that is `CONFIRMED` has its `start_at` earlier than this
    appointment's `end_at` while this appointment's `start_at` is earlier than that
    appointment's `end_at`."

    Design: Difficulty/resource_temporal_overlap/customer_halfopen_double_booking_rejected
    """
    customer = register_customer(api)
    spec1 = create_specialist(api, specialties=["ADAPTIVE"], buffer_minutes=0)
    spec2 = create_specialist(api, specialties=["ADAPTIVE"], buffer_minutes=0)
    first = book_appointment(api, customer["id"], spec1["id"],
                             "2026-07-06T10:00:00Z", "2026-07-06T11:00:00Z")
    confirm_appointment(api, first["id"])
    second = book_appointment(api, customer["id"], spec2["id"],
                              "2026-07-06T10:30:00Z", "2026-07-06T11:30:00Z")
    resp = api.transition_appointment(second["id"], {"action": "CONFIRM"}, SM)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_DOUBLE_BOOKED.value)


def test_customer_adjacent_halfopen_booking_confirms(api):
    """PRD §3.5: "The customer is an unbuffered resource compared on the raw
    half-open intervals: a conflict exists if any other appointment for the same
    `customer_id` that is `CONFIRMED` has its `start_at` earlier than this
    appointment's `end_at` while this appointment's `start_at` is earlier than that
    appointment's `end_at`."

    Design: Difficulty/resource_temporal_overlap/customer_halfopen_double_booking_rejected
    """
    customer = register_customer(api)
    spec1 = create_specialist(api, specialties=["ADAPTIVE"], buffer_minutes=0)
    spec2 = create_specialist(api, specialties=["ADAPTIVE"], buffer_minutes=0)
    first = book_appointment(api, customer["id"], spec1["id"],
                             "2026-07-06T10:00:00Z", "2026-07-06T11:00:00Z")
    confirm_appointment(api, first["id"])
    # [11:00,12:00) does not intersect [10:00,11:00) under half-open semantics.
    second = book_appointment(api, customer["id"], spec2["id"],
                              "2026-07-06T11:00:00Z", "2026-07-06T12:00:00Z")
    data = validate_success(api.transition_appointment(second["id"], {"action": "CONFIRM"}, SM))
    assert data["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Corner: complete before end
# ---------------------------------------------------------------------------
def test_complete_before_end_returns_not_ended(api):
    """PRD §3.5: "A specialist completes it, moving `CONFIRMED` to `COMPLETED`, only
    once the clock has reached or passed its `end_at`; completing early is rejected
    with `ERR_APPOINTMENT_NOT_ENDED`."

    Design: Corner/state_machines/appointment_complete_before_end_returns_not_ended
    """
    customer = register_customer(api)
    specialist = create_specialist(api, specialties=["ADAPTIVE"])
    appt = book_appointment(api, customer["id"], specialist["id"],
                            "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z")
    confirm_appointment(api, appt["id"])
    # Clock is still at the 2026-07-01 startup default, before end_at.
    resp = api.transition_appointment(
        appt["id"], {"action": "COMPLETE"}, make_fit_specialist_headers(specialist["id"])
    )
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_ENDED.value)
    result = validate_success(api.get_appointment(appt["id"], SM))
    assert result["status"] == "CONFIRMED"
