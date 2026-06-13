"""Enrollment gate ordering, cross-entity state dependencies, and boundary precision.

Covers the priority-ordered gate evaluation (§3.6), the Enrollment->ClassSeries and
MakeupBooking->ClassSession state pairs (§3.6/§3.11), the seat boundary (§3.5/§3.6), and the
half-open vaccination-expiry boundary on reinstate (§3.2/§3.6).
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_owner_headers, make_trainer_headers,
    create_owner, create_dog, vaccinate_fully, create_trainer, create_series_draft,
    create_session, open_series, get_series, enroll, set_clock,
    create_enrollment_payload, create_vaccination_payload,
    setup_missed_provider_with_makeup_slot,
)


def test_series_not_open_beats_vaccination_gate(api):
    """PRD §3.6: "These checks are evaluated in their priority order, so that the failure
    surfaced is the highest-priority one applicable: header validity first, then role
    permission, then existence of every referenced id, then dog ownership, then the
    series-state check, then the business constraints (including private-first and the
    duplicate check), then the vaccination safety gate".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_series_not_open_beats_vaccination
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)  # NO vaccinations -> posture UNKNOWN (not COMPLIANT)
    trainer = create_trainer(certified_levels=["BASIC"])
    # DRAFT series (never opened); single session present.
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")

    res = api.create_enrollment(
        create_enrollment_payload(dog["id"], series["id"], series["version"]),
        make_owner_headers(owner["id"]))
    # State check (series not OPEN) outranks the safety gate (unvaccinated dog).
    validate_error(res, "ERR_SERIES_NOT_OPEN", expected_status=409)


def test_series_not_open_beats_vaccination_even_for_private(api):
    """PRD §3.6: "The series must be `OPEN`; otherwise the enrollment is rejected with
    `ERR_SERIES_NOT_OPEN`. The dog's `vaccination_posture` must be `COMPLIANT` evaluated
    against the date of the series' first non-makeup session; a non-compliant dog is rejected
    with `ERR_VACCINATION_PREREQUISITE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_series_not_open_beats_vaccination
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)  # unvaccinated
    trainer = create_trainer(certified_levels=["BASIC"], handles_private=True)
    series = create_series_draft(level="BASIC", modality="PRIVATE", capacity=1,
                                 session_count=1, list_price_cents=30000, credit_cost=4)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")

    res = api.create_enrollment(
        create_enrollment_payload(dog["id"], series["id"], series["version"]),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_SERIES_NOT_OPEN", expected_status=409)


def test_enroll_into_closed_series_rejected(api):
    """PRD §3.6: "The series must be `OPEN`; otherwise the enrollment is rejected with
    `ERR_SERIES_NOT_OPEN`." PRD §3.4: "After closing, no further seat-claiming enrollment is
    accepted, but enrollments already `ACTIVE` continue toward graduation unaffected."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_series_open_pair_enrollment_series
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    api.close_class_series(series["id"], TEST_USERS["admin_manager_headers"])
    closed = get_series(series["id"])

    res = api.create_enrollment(
        create_enrollment_payload(dog["id"], series["id"], closed["version"]),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_SERIES_NOT_OPEN", expected_status=409)


def test_enroll_into_open_series_succeeds_cross_entity(api):
    """PRD §3.6: "Once every gate passes, seat availability decides the outcome: if the series
    has at least one seat available the enrollment becomes `ACTIVE`".

    The complement of the closed-series rejection: while the referenced series is OPEN the
    enrollment is admitted, confirming the dependency is on series.status.

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_series_open_pair_enrollment_series
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)

    res = api.create_enrollment(
        create_enrollment_payload(dog["id"], series["id"], series["version"]),
        make_owner_headers(owner["id"]))
    enr = validate_success(res, 201)
    assert enr["status"] == "ACTIVE"


def test_makeup_complete_requires_session_completed(api):
    """PRD §3.11: "A trainer completes a confirmed booking once the makeup has been delivered,
    moving `CONFIRMED → COMPLETED`. Completion requires that the makeup session's own status
    be `COMPLETED`, or it is rejected with `ERR_MAKEUP_SESSION_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/makeup_complete_requires_session_completed_pair_makeup_session
    """
    bundle = setup_missed_provider_with_makeup_slot()
    makeup, trainer = bundle["makeup_booking"], bundle["trainer"]
    # Confirm the booking; the makeup session itself is still SCHEDULED.
    api.confirm_makeup_booking(makeup["id"], TEST_USERS["front_desk_headers"])

    res = api.complete_makeup_booking(makeup["id"], make_trainer_headers(trainer["id"]))
    validate_error(res, "ERR_MAKEUP_SESSION_NOT_COMPLETED", expected_status=409)


def test_makeup_confirm_succeeds_when_session_scheduled(api):
    """PRD §3.11: "The named makeup session must itself be a reserved makeup slot — its
    `is_makeup_slot` must be true — and it must be `SCHEDULED`; failing either is rejected
    with `ERR_INVALID_MAKEUP_SLOT`."

    The CONFIRMED state is reachable while the slot is SCHEDULED; it is only the *complete*
    step that additionally requires the slot to be COMPLETED — confirming the pairing is on
    the makeup ClassSession's status.

    Design: Difficulty/cross_entity_state_dependency/makeup_complete_requires_session_completed_pair_makeup_session
    """
    bundle = setup_missed_provider_with_makeup_slot()
    makeup = bundle["makeup_booking"]
    res = api.confirm_makeup_booking(makeup["id"], TEST_USERS["front_desk_headers"])
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED", "confirm permitted while slot is SCHEDULED"


def test_seat_boundary_second_enroll_waitlisted_at_zero_seats(api):
    """PRD §3.6: "if the series has at least one seat available the enrollment becomes
    `ACTIVE`; if all gates pass but `seats_available` is 0, the enrollment is instead created
    `WAITLISTED`".

    Design: Difficulty/boundary_precision_check/capacity_full_seat_boundary_on_enrollments
    """
    set_clock()
    owner = create_owner()
    dog1 = create_dog(owner, name="D1")
    dog2 = create_dog(owner, name="D2")
    vaccinate_fully(owner, dog1)
    vaccinate_fully(owner, dog2)
    trainer = create_trainer(certified_levels=["BASIC"], handles_private=True)
    series = create_series_draft(level="BASIC", modality="PRIVATE", capacity=1,
                                 session_count=1, list_price_cents=30000, credit_cost=4)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)

    enr1 = enroll(owner, dog1, series, series_version=series["version"])
    assert enr1["status"] == "ACTIVE", "seats_available was 1 (boundary X), seat claimed"
    enr2 = enroll(owner, dog2, series)  # fresh version; seats_available now 0
    assert enr2["status"] == "WAITLISTED", "seats_available was exactly 0, no seat to claim"


def test_seat_boundary_first_enroll_active_when_one_seat(api):
    """PRD §3.5: "The `seats_available` figure is the series `capacity` minus that
    seat-holding count." PRD §3.6: "if the series has at least one seat available the
    enrollment becomes `ACTIVE`".

    Design: Difficulty/boundary_precision_check/capacity_full_seat_boundary_on_enrollments
    """
    set_clock()
    owner = create_owner()
    dog1 = create_dog(owner, name="D1")
    vaccinate_fully(owner, dog1)
    trainer = create_trainer(certified_levels=["BASIC"], handles_private=True)
    series = create_series_draft(level="BASIC", modality="PRIVATE", capacity=1,
                                 session_count=1, list_price_cents=30000, credit_cost=4)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    assert series["seats_available"] == 1, "capacity 1 initialized at open"

    enr1 = enroll(owner, dog1, series, series_version=series["version"])
    assert enr1["status"] == "ACTIVE"


def test_vaccination_expiry_half_open_boundary_on_reinstate(api):
    """PRD §3.2: "A dose is considered to provide coverage on the half-open interval running
    from `administered_on` up to but not including `expires_on`: a record whose `expires_on`
    equals the date being checked does **not** cover that date." PRD §3.6: "A `FrontDesk` or
    `AdminManager` reinstates a suspended enrollment, moving `SUSPENDED → ACTIVE`, but only
    once the dog's `vaccination_posture` is `COMPLIANT` again; reinstating a still-non-compliant
    dog is rejected with `ERR_VACCINATION_PREREQUISITE`."

    Design: Difficulty/boundary_precision_check/vaccination_expiry_half_open_boundary_on_reinstate
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner()
    dog = create_dog(owner)
    records = vaccinate_fully(owner, dog)  # all expire 2027-01-01, well after clock
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-06-15T09:00:00Z", "2026-06-15T10:00:00Z")
    series = open_series(series)
    enr = enroll(owner, dog, series, series_version=series["version"])

    # Void RABIES -> posture NONCOMPLIANT -> enrollment SUSPENDED.
    api.void_vaccination(records["RABIES"]["id"], TEST_USERS["front_desk_headers"])
    suspended = validate_success(api.get_enrollment(enr["id"], make_owner_headers(owner["id"])), 200)
    assert suspended["status"] == "SUSPENDED"

    # Replacement RABIES whose coverage ends EXACTLY at the current clock date (2026-06-01):
    # half-open means it does NOT cover 2026-06-01, so posture stays NONCOMPLIANT.
    api.create_vaccination(
        dog["id"],
        create_vaccination_payload("RABIES", administered_on="2025-06-01", expires_on="2026-06-01"),
        make_owner_headers(owner["id"]))

    res = api.reinstate_enrollment(enr["id"], TEST_USERS["front_desk_headers"])
    validate_error(res, "ERR_VACCINATION_PREREQUISITE", expected_status=422)


def test_vaccination_expiry_one_day_after_clock_covers_reinstate(api):
    """PRD §3.2: "A type is covered at the reference date when at least one non-voided record
    of that type has an `administered_on` on or before the reference date and an `expires_on`
    strictly after it." PRD §3.6: "A `FrontDesk` or `AdminManager` reinstates a suspended
    enrollment, moving `SUSPENDED → ACTIVE`, but only once the dog's `vaccination_posture` is
    `COMPLIANT` again".

    Boundary X+1: a replacement RABIES expiring one day AFTER the clock date (2026-06-02) does
    cover 2026-06-01, restoring COMPLIANT, so reinstate succeeds.

    Design: Difficulty/boundary_precision_check/vaccination_expiry_half_open_boundary_on_reinstate
    """
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner()
    dog = create_dog(owner)
    records = vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-06-15T09:00:00Z", "2026-06-15T10:00:00Z")
    series = open_series(series)
    enr = enroll(owner, dog, series, series_version=series["version"])

    api.void_vaccination(records["RABIES"]["id"], TEST_USERS["front_desk_headers"])
    suspended = validate_success(api.get_enrollment(enr["id"], make_owner_headers(owner["id"])), 200)
    assert suspended["status"] == "SUSPENDED"

    # Replacement RABIES whose coverage ends 2026-06-02 (strictly after the clock date) covers
    # 2026-06-01 -> posture COMPLIANT again.
    api.create_vaccination(
        dog["id"],
        create_vaccination_payload("RABIES", administered_on="2025-06-01", expires_on="2026-06-02"),
        make_owner_headers(owner["id"]))

    res = api.reinstate_enrollment(enr["id"], TEST_USERS["front_desk_headers"])
    reinstated = validate_success(res, 200)
    assert reinstated["status"] == "ACTIVE", "coverage strictly past clock date restores COMPLIANT"
