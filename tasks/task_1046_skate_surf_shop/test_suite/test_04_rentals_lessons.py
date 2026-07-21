"""Rentals and lessons: charge computation, the 14-day length bound, unit and
instructor calendar semantics, the length-vs-overlap precedence, and the
lesson-confirm linked-rental readiness precondition.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, get_success_data,
    create_member, create_rental_unit, create_instructor,
    create_checked_out_rental, create_reserved_rental, create_booked_lesson,
    create_rental_payload, create_lesson_payload, set_clock,
)

SM = TEST_USERS["shop_manager_headers"]
ASSOC = TEST_USERS["associate_headers"]


def test_rental_charge_base_plus_late_fee(api):
    """PRD §3.5: "`rental_total_cents` is the unit's `daily_rate_cents` times the
    inclusive rental duration in days (the difference between `end_date` and
    `start_date`, plus one); the number of late days is the difference between the
    current clock date and `end_date` but never less than zero; and `late_fee_cents`
    is that late-day count times 1500 cents per day."

    Design: Corner/calculations/rental_charge_base_plus_late_fee
    """
    rental, member, unit = create_checked_out_rental(
        api, start_date="2026-07-10", end_date="2026-07-12", daily_rate_cents=2500)
    set_clock(api, "2026-07-14T09:00:00Z")
    resp = api.return_rental(rental["id"], ASSOC)
    data = validate_success(resp, 200)
    assert data["rental_total_cents"] == 7500
    assert data["late_fee_cents"] == 3000
    assert data["status"] == "RETURNED"


def test_rental_exactly_14_days_reserved(api):
    """PRD §2.8: "the inclusive duration in days, counted as the difference between
    `end_date` and `start_date` plus one, may not exceed 14 days, and a longer request
    is rejected with `ERR_RENTAL_TOO_LONG`."

    Design: Difficulty/boundary_precision_check/rental_duration_exactly_max_days_allowed
    """
    member = create_member(api)
    unit = create_rental_unit(api, daily_rate_cents=1000, kind="SKATEBOARD")
    resp = api.create_rental(create_rental_payload(
        member["id"], unit["id"], "2026-07-01", "2026-07-14"), ASSOC)
    data = validate_success(resp, 201)
    assert data["status"] == "RESERVED"


def test_rental_15_days_rejected_too_long(api):
    """PRD §2.8: "the inclusive duration in days, counted as the difference between
    `end_date` and `start_date` plus one, may not exceed 14 days, and a longer request
    is rejected with `ERR_RENTAL_TOO_LONG`."

    Design: Difficulty/boundary_precision_check/rental_duration_exactly_max_days_allowed
    """
    member = create_member(api)
    unit = create_rental_unit(api, daily_rate_cents=1000, kind="SKATEBOARD")
    resp = api.create_rental(create_rental_payload(
        member["id"], unit["id"], "2026-07-01", "2026-07-15"), ASSOC)
    validate_error(resp, ApiErrorId.ERR_RENTAL_TOO_LONG.value)


def test_rental_too_long_overlapping_returns_too_long(api):
    """PRD §2.5: "the system evaluates checks in a fixed priority order and returns
    the error for the first check that fails."
    PRD §2.5: "7. **Business constraints** — duplicate registration
    (`ERR_DUPLICATE_REGISTRATION`, 409), event capacity (`ERR_EVENT_FULL`, 409),
    rental length (`ERR_RENTAL_TOO_LONG`, 422), and stock sufficiency
    (`ERR_INSUFFICIENT_STOCK`, 409)."
    PRD §2.5: "8. **Temporal constraints** — instructor calendar
    (`ERR_INSTRUCTOR_UNAVAILABLE`, 409), bay separation (`ERR_BAY_UNAVAILABLE`, 409),
    and rental-unit calendar (`ERR_UNIT_UNAVAILABLE`, 409)."

    Design: Difficulty/priority_pair_validation_conflict/rental_too_long_beats_unit_unavailable
    """
    rental, member, unit = create_reserved_rental(
        api, start_date="2026-07-10", end_date="2026-07-12")
    resp = api.create_rental(create_rental_payload(
        member["id"], unit["id"], "2026-07-11", "2026-07-30"), ASSOC)
    validate_error(resp, ApiErrorId.ERR_RENTAL_TOO_LONG.value)


def test_rental_too_long_precedence_status_422(api):
    """PRD §2.5: "the system evaluates checks in a fixed priority order and returns
    the error for the first check that fails."
    PRD §2.8: "a longer request is rejected with `ERR_RENTAL_TOO_LONG`."

    Design: Difficulty/priority_pair_validation_conflict/rental_too_long_beats_unit_unavailable
    """
    rental, member, unit = create_reserved_rental(
        api, start_date="2026-07-10", end_date="2026-07-12")
    resp = api.create_rental(create_rental_payload(
        member["id"], unit["id"], "2026-07-11", "2026-07-30"), ASSOC)
    # Business-constraint length check (prio 7) pre-empts the temporal overlap (prio 8):
    # HTTP 422 (ERR_RENTAL_TOO_LONG) rather than 409 (ERR_UNIT_UNAVAILABLE).
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_RENTAL_TOO_LONG.value)


def test_rental_unit_overlap_unavailable(api):
    """PRD §2.8: "two rentals conflict when their `[start_date, end_date]` ranges share
    any day, including a shared endpoint day. Only rentals in `RESERVED` or
    `CHECKED_OUT` status occupy the unit; a conflict is rejected with `ERR_UNIT_UNAVAILABLE`."

    Design: Corner/errors/rental_unit_overlap_returns_unit_unavailable
    """
    rental, member, unit = create_reserved_rental(
        api, start_date="2026-07-10", end_date="2026-07-12")
    resp = api.create_rental(create_rental_payload(
        member["id"], unit["id"], "2026-07-11", "2026-07-13"), ASSOC)
    validate_error(resp, ApiErrorId.ERR_UNIT_UNAVAILABLE.value)


def test_instructor_adjacent_lesson_allowed(api):
    """PRD §2.8: "two lessons conflict when their `[start_at, end_at)` ranges overlap,
    but abutting lessons where one ends exactly when the next begins do not conflict."

    Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_allowed
    """
    lesson, member, instructor = create_booked_lesson(
        api, discipline="SKATE",
        start_at="2026-07-09T10:00:00Z", end_at="2026-07-09T11:00:00Z")
    resp = api.create_lesson(create_lesson_payload(
        member["id"], instructor["id"], "SKATE",
        "2026-07-09T11:00:00Z", "2026-07-09T12:00:00Z", 5000), ASSOC)
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


def test_instructor_adjacent_lesson_before_existing_allowed(api):
    """PRD §2.8: "two lessons conflict when their `[start_at, end_at)` ranges overlap,
    but abutting lessons where one ends exactly when the next begins do not conflict."

    Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_allowed
    """
    lesson, member, instructor = create_booked_lesson(
        api, discipline="SKATE",
        start_at="2026-07-09T11:00:00Z", end_at="2026-07-09T12:00:00Z")
    resp = api.create_lesson(create_lesson_payload(
        member["id"], instructor["id"], "SKATE",
        "2026-07-09T10:00:00Z", "2026-07-09T11:00:00Z", 5000), ASSOC)
    data = validate_success(resp, 201)
    assert data["status"] == "BOOKED"


def test_instructor_overlap_unavailable(api):
    """PRD §3.5: "no calendar conflict on that instructor per the half-open rule of
    §2.8 (else `ERR_INSTRUCTOR_UNAVAILABLE`)."

    Design: Corner/errors/instructor_overlap_returns_unavailable
    """
    lesson, member, instructor = create_booked_lesson(
        api, discipline="SKATE",
        start_at="2026-07-09T10:00:00Z", end_at="2026-07-09T11:00:00Z")
    resp = api.create_lesson(create_lesson_payload(
        member["id"], instructor["id"], "SKATE",
        "2026-07-09T10:30:00Z", "2026-07-09T11:30:00Z", 5000), ASSOC)
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_UNAVAILABLE.value)


def test_confirm_lesson_cancelled_rental_not_ready(api):
    """PRD §3.5: "Confirming a lesson is an `Instructor`-or-`ShopManager` action
    allowed only from `BOOKED`, and it additionally requires that every rental linked
    to this lesson be in `RESERVED` or `CHECKED_OUT` status, else `ERR_RENTAL_NOT_READY`;
    on success `confirmed_at` is stamped."

    Design: Difficulty/cross_entity_state_dependency/lesson_confirm_requires_linked_rental_ready
    """
    lesson, member, instructor = create_booked_lesson(
        api, discipline="SURF", fee_cents=5000,
        start_at="2026-07-08T10:00:00Z", end_at="2026-07-08T11:00:00Z")
    unit = create_rental_unit(api, daily_rate_cents=800, kind="WETSUIT")
    rental = get_success_data(api.create_rental(create_rental_payload(
        member["id"], unit["id"], "2026-07-08", "2026-07-08", lesson_id=lesson["id"]), ASSOC))
    api.cancel_rental(rental["id"], ASSOC)
    resp = api.confirm_lesson(lesson["id"], SM)
    validate_error(resp, ApiErrorId.ERR_RENTAL_NOT_READY.value)


def test_confirm_lesson_reserved_rental_succeeds(api):
    """PRD §3.5: "Confirming a lesson is an `Instructor`-or-`ShopManager` action
    allowed only from `BOOKED`, and it additionally requires that every rental linked
    to this lesson be in `RESERVED` or `CHECKED_OUT` status, else `ERR_RENTAL_NOT_READY`;
    on success `confirmed_at` is stamped."

    Design: Difficulty/cross_entity_state_dependency/lesson_confirm_requires_linked_rental_ready
    """
    lesson, member, instructor = create_booked_lesson(
        api, discipline="SURF", fee_cents=5000,
        start_at="2026-07-08T10:00:00Z", end_at="2026-07-08T11:00:00Z")
    unit = create_rental_unit(api, daily_rate_cents=800, kind="WETSUIT")
    get_success_data(api.create_rental(create_rental_payload(
        member["id"], unit["id"], "2026-07-08", "2026-07-08", lesson_id=lesson["id"]), ASSOC))
    resp = api.confirm_lesson(lesson["id"], SM)
    data = validate_success(resp, 200)
    assert data["status"] == "CONFIRMED"
