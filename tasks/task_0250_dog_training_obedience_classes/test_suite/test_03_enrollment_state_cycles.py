"""Enrollment cyclic state machine, makeup-booking branching, and vaccination-driven
suspension cascade.

Covers WAITLISTED<->ACTIVE promotion (§3.6), the REQUESTED->{CONFIRMED,REJECTED} branch
(§3.11), and the vaccination-void depth-2 ACTIVE->SUSPENDED cascade (§3.2/§3.6).
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    TEST_USERS, make_owner_headers, make_trainer_headers,
    setup_enroll_ready_private, setup_missed_provider_with_makeup_slot,
    setup_enroll_ready_group, enroll,
    create_owner, create_dog, vaccinate_fully, create_trainer, create_series_draft,
    create_session, open_series, get_series, set_clock,
    attendance_for_session,
)


def test_waitlisted_promoted_to_active_after_seat_frees(api):
    """PRD §3.6: "A `WAITLISTED` enrollment is advanced to a seat by a `FrontDesk` or
    `AdminManager` promoting it, moving `WAITLISTED → ACTIVE`, or by the system automatically
    when a seat is released." PRD §3.6: "if all gates pass but `seats_available` is 0, the
    enrollment is instead created `WAITLISTED`, holding no seat".

    Design: Difficulty/non_linear_state_machine/enrollment_active_to_waitlisted_cycle
    """
    set_clock()
    owner = create_owner()
    dogA = create_dog(owner, name="DogA")
    dogB = create_dog(owner, name="DogB")
    vaccinate_fully(owner, dogA)
    vaccinate_fully(owner, dogB)
    trainer = create_trainer(certified_levels=["BASIC"], handles_private=True)
    series = create_series_draft(level="BASIC", modality="PRIVATE", capacity=1,
                                 session_count=1, list_price_cents=30000, credit_cost=4)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)

    enrA = enroll(owner, dogA, series, series_version=series["version"])
    assert enrA["status"] == "ACTIVE", "first dog claims the single seat"
    enrB = enroll(owner, dogB, series)  # reads fresh version; seat is full
    assert enrB["status"] == "WAITLISTED", "capacity 1 already full"

    # Free the seat, then promote B.
    api.withdraw_enrollment(enrA["id"], make_owner_headers(owner["id"]))
    res = api.promote_enrollment(enrB["id"], TEST_USERS["front_desk_headers"])
    promoted = validate_success(res, 200)
    assert promoted["status"] == "ACTIVE", "promoted after A's seat freed"


def test_second_enrollment_waitlisted_when_capacity_full(api):
    """PRD §3.6: "if all gates pass but `seats_available` is 0, the enrollment is instead
    created `WAITLISTED`, holding no seat, incurring no charge and no credit debit until it is
    later promoted."

    Design: Difficulty/non_linear_state_machine/enrollment_active_to_waitlisted_cycle
    """
    set_clock()
    owner = create_owner()
    dogA = create_dog(owner, name="DogA")
    dogB = create_dog(owner, name="DogB")
    vaccinate_fully(owner, dogA)
    vaccinate_fully(owner, dogB)
    trainer = create_trainer(certified_levels=["BASIC"], handles_private=True)
    series = create_series_draft(level="BASIC", modality="PRIVATE", capacity=1,
                                 session_count=1, list_price_cents=30000, credit_cost=4)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)

    enroll(owner, dogA, series, series_version=series["version"])
    enrB = enroll(owner, dogB, series)
    assert enrB["status"] == "WAITLISTED"
    assert enrB["price_charged_cents"] == 0, "no charge until promotion"


def test_makeup_reject_leaves_source_attendance_unchanged(api):
    """PRD §3.11: "The same booking may instead be rejected by a `FrontDesk` or
    `AdminManager`, moving `REQUESTED → REJECTED`, in which case the source attendance record
    is left unchanged (it remains `MISSED_PROVIDER` or `ABSENT`)."

    Design: Difficulty/non_linear_state_machine/makeup_booking_branching_confirm_vs_reject
    """
    bundle = setup_missed_provider_with_makeup_slot()
    owner, makeup, missed_att = bundle["owner"], bundle["makeup_booking"], bundle["missed_attendance"]

    res = api.reject_makeup_booking(makeup["id"], TEST_USERS["front_desk_headers"])
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"

    att = validate_success(
        api.get_attendance_record(missed_att["id"], make_owner_headers(owner["id"])), 200)
    assert att["state"] == "MISSED_PROVIDER", "reject leaves source unchanged (NOT MAKEUP_PENDING)"


def test_makeup_confirm_sets_source_attendance_pending(api):
    """PRD §3.11: "On success, the source attendance record moves to `MAKEUP_PENDING`."

    Design: Difficulty/non_linear_state_machine/makeup_booking_branching_confirm_vs_reject
    """
    bundle = setup_missed_provider_with_makeup_slot()
    owner, makeup, missed_att = bundle["owner"], bundle["makeup_booking"], bundle["missed_attendance"]

    res = api.confirm_makeup_booking(makeup["id"], TEST_USERS["front_desk_headers"])
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED"

    att = validate_success(
        api.get_attendance_record(missed_att["id"], make_owner_headers(owner["id"])), 200)
    assert att["state"] == "MAKEUP_PENDING", "confirm moves source attendance to MAKEUP_PENDING"


def test_vaccination_void_recomputes_posture_noncompliant(api):
    """PRD §3.2: "Voiding a record — setting `voided` to true — likewise recomputes it.
    Either change can flip the posture." PRD §3.2: "if the dog has at least one non-voided
    record but not all three types are covered, the posture is `NONCOMPLIANT`".

    Design: Difficulty/transitive_cascade/vaccination_void_depth2_enrollment_suspend
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)
    records = vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    enroll(owner, dog, series, series_version=series["version"])

    api.void_vaccination(records["RABIES"]["id"], TEST_USERS["front_desk_headers"])
    refetched = validate_success(api.get_dog(dog["id"], make_owner_headers(owner["id"])), 200)
    assert refetched["vaccination_posture"] == "NONCOMPLIANT", "voiding RABIES drops coverage"


def test_vaccination_void_suspends_active_enrollment(api):
    """PRD §3.2: "when a recomputation flips a dog's posture to `NONCOMPLIANT`, every one of
    that dog's enrollments currently in `ACTIVE` is automatically suspended, moving
    `ACTIVE → SUSPENDED`."

    Design: Difficulty/transitive_cascade/vaccination_void_depth2_enrollment_suspend
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)
    records = vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    enr = enroll(owner, dog, series, series_version=series["version"])
    assert enr["status"] == "ACTIVE"

    api.void_vaccination(records["RABIES"]["id"], TEST_USERS["front_desk_headers"])
    refetched = validate_success(api.get_enrollment(enr["id"], make_owner_headers(owner["id"])), 200)
    assert refetched["status"] == "SUSPENDED", "posture flip cascades ACTIVE -> SUSPENDED"
