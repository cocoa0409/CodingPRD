"""Enrollment validations, payment guards, package lifecycle errors, and RBAC.

Corner-design coverage for the `validations`, `errors`, and `rbac` sections.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    TEST_USERS, make_owner_headers, make_trainer_headers,
    create_owner, create_dog, vaccinate_fully, create_trainer, create_series_draft,
    create_session, open_series, get_series, enroll, set_clock, create_package,
    create_owner_payload, create_trainer_payload, create_enrollment_payload,
    create_behavioral_intake_payload, create_makeup_booking_payload, mark_attendance_payload,
    setup_enroll_ready_group, attendance_for_session,
)


# ─── validations section ────────────────────────────────────────────────────────
def test_duplicate_enrollment_same_dog_series_rejected(api):
    """PRD §3.6: "The dog must not already hold a non-terminal enrollment for the same series —
    at most one enrollment per dog-and-series pair may be in any status other than `WITHDRAWN`
    or `GRADUATED`, and a duplicate is rejected with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/validations/duplicate_enrollment_same_dog_series
    """
    bundle = setup_enroll_ready_group(session_count=1, capacity=5)
    owner, dog, series = bundle["owner"], bundle["dog"], bundle["series"]
    enroll(owner, dog, series, series_version=series["version"])
    fresh = get_series(series["id"])
    res = api.create_enrollment(
        create_enrollment_payload(dog["id"], series["id"], fresh["version"]),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_DUPLICATE_ENROLLMENT", expected_status=409)


def test_duplicate_owner_email_rejected(api):
    """PRD §3.1: "The `email` must be unique across all owners; an attempt to create a second
    owner with an `email` already in use is rejected with `ERR_DUPLICATE_OWNER_EMAIL`."

    Design: Corner/validations/duplicate_owner_email_rejected
    """
    api.create_owner(create_owner_payload(email="dup@example.com", full_name="First"),
                     TEST_USERS["front_desk_headers"])
    res = api.create_owner(create_owner_payload(email="dup@example.com", full_name="Second"),
                           TEST_USERS["front_desk_headers"])
    validate_error(res, "ERR_DUPLICATE_OWNER_EMAIL", expected_status=409)


def test_prerequisite_level_not_met_rejected(api):
    """PRD §3.6: "The dog's `highest_completed_level` must be at least the series'
    `prerequisite_level`; if the dog has not completed the required prior level the request is
    rejected with `ERR_PREREQUISITE_LEVEL_NOT_MET`."

    Design: Corner/validations/prerequisite_level_not_met
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)  # highest_completed_level NONE
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["INTERMEDIATE"])
    series = create_series_draft(level="INTERMEDIATE", prerequisite_level="BASIC",
                                 modality="GROUP", capacity=5, session_count=1,
                                 list_price_cents=18000, credit_cost=3)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    res = api.create_enrollment(
        create_enrollment_payload(dog["id"], series["id"], series["version"]),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_PREREQUISITE_LEVEL_NOT_MET", expected_status=422)


def test_flagged_dog_group_requires_private_first(api):
    """PRD §3.6: "If the series' `modality` is `GROUP` and the dog's `intake_status` is
    `FLAGGED`, the dog must already hold a `GRADUATED` enrollment in some `PRIVATE` series;
    lacking that, the group enrollment is rejected with `ERR_PRIVATE_FIRST_REQUIRED`."

    Design: Corner/validations/flagged_dog_group_requires_private_first
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)
    # Flag the dog via a bite_history intake.
    api.create_behavioral_intake(
        dog["id"],
        create_behavioral_intake_payload(reactivity_score=2, bite_history=True,
                                         recommended_level="BASIC"),
        TEST_USERS["trainer_headers"])
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    res = api.create_enrollment(
        create_enrollment_payload(dog["id"], series["id"], series["version"]),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_PRIVATE_FIRST_REQUIRED", expected_status=422)


def test_insufficient_credits_on_package_enrollment(api):
    """PRD §3.6: "it must hold enough credits — its `credits_remaining` must be at least the
    series' `credit_cost` — or the enrollment is rejected with `ERR_INSUFFICIENT_CREDITS`."

    Design: Corner/validations/insufficient_credits_on_package_enrollment
    """
    set_clock()
    owner = create_owner()
    dogA = create_dog(owner, name="IcA")
    dogB = create_dog(owner, name="IcB")
    vaccinate_fully(owner, dogA)
    vaccinate_fully(owner, dogB)
    pkg = create_package(owner, tier="STARTER")  # 4 credits
    trainer = create_trainer(certified_levels=["BASIC"], handles_private=True)

    # Series A: 2-credit GROUP enroll leaves 2 credits (package stays ACTIVE).
    seriesA = create_series_draft(level="BASIC", modality="GROUP", capacity=5,
                                  session_count=1, list_price_cents=12000, credit_cost=2)
    create_session(seriesA, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    seriesA = open_series(seriesA)
    enroll(owner, dogA, seriesA, payment_method="PACKAGE", package_id=pkg["id"],
           series_version=seriesA["version"])

    # Series B: 4-credit PRIVATE enroll needs 4 > 2 remaining.
    seriesB = create_series_draft(level="BASIC", modality="PRIVATE", capacity=1,
                                  session_count=1, list_price_cents=30000, credit_cost=4)
    create_session(seriesB, trainer, 1, "2026-07-03T09:00:00Z", "2026-07-03T10:00:00Z")
    seriesB = open_series(seriesB)
    res = api.create_enrollment(
        create_enrollment_payload(dogB["id"], seriesB["id"], seriesB["version"],
                                  payment_method="PACKAGE", package_id=pkg["id"]),
        make_owner_headers(owner["id"]))
    validate_error(res, "ERR_INSUFFICIENT_CREDITS", expected_status=402)


# ─── errors section ─────────────────────────────────────────────────────────────
def test_package_required_for_credit_payment(api):
    """PRD §3.6: "A `package_id` is required when `payment_method` is `PACKAGE` and must be
    null when it is `CASH`; violating either shape is rejected with
    `ERR_PACKAGE_REQUIRED_FOR_CREDIT`."

    Design: Corner/errors/package_required_for_credit_payment
    """
    bundle = setup_enroll_ready_group(session_count=1)
    res = api.create_enrollment(
        create_enrollment_payload(bundle["dog"]["id"], bundle["series"]["id"],
                                  bundle["series"]["version"], payment_method="PACKAGE"),
        make_owner_headers(bundle["owner"]["id"]))
    validate_error(res, "ERR_PACKAGE_REQUIRED_FOR_CREDIT", expected_status=422)


def test_expire_package_in_use_rejected(api):
    """PRD §3.12: "Expiry is blocked while any enrollment in `ACTIVE`, `WAITLISTED`, or
    `SUSPENDED` still references the package; such a request is rejected with
    `ERR_PACKAGE_IN_USE`."

    Design: Corner/errors/expire_package_in_use_rejected
    """
    bundle = setup_enroll_ready_group(session_count=1, credit_cost=2)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="VALUE")
    enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
           package_id=pkg["id"], series_version=bundle["series"]["version"])
    res = api.expire_package(pkg["id"], TEST_USERS["admin_manager_headers"])
    validate_error(res, "ERR_PACKAGE_IN_USE", expected_status=409)


def test_makeup_not_eligible_for_present_attendance(api):
    """PRD §3.11: "The source attendance record must be `makeup_eligible`, or the confirm is
    rejected with `ERR_MAKEUP_NOT_ELIGIBLE`." PRD §3.8: "An attendance record is
    `makeup_eligible` when its `state` is `MISSED_PROVIDER`, or when its `state` is `ABSENT`
    and the owning series' `modality` is `PRIVATE`".

    Design: Corner/errors/makeup_not_eligible_for_present_attendance
    """
    set_clock()
    owner = create_owner()
    dog = create_dog(owner)
    vaccinate_fully(owner, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=2)
    sess1 = create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    create_session(series, trainer, 2, "2026-07-02T09:00:00Z", "2026-07-02T10:00:00Z")
    makeup_session = create_session(series, trainer, 3, "2026-07-08T09:00:00Z",
                                    "2026-07-08T10:00:00Z", is_makeup_slot=True)
    series = open_series(series)
    enroll(owner, dog, series, series_version=series["version"])

    # Mark session 1 PRESENT (not makeup_eligible), then request a makeup against it.
    t_headers = make_trainer_headers(trainer["id"])
    api.start_class_session(sess1["id"], t_headers)
    att = attendance_for_session(sess1, t_headers)
    api.mark_attendance(sess1["id"], mark_attendance_payload(att["id"], "PRESENT"), t_headers)
    makeup = get_success_data(api.create_makeup_booking(
        create_makeup_booking_payload(att["id"], makeup_session["id"]),
        make_owner_headers(owner["id"])))

    res = api.confirm_makeup_booking(makeup["id"], TEST_USERS["front_desk_headers"])
    validate_error(res, "ERR_MAKEUP_NOT_ELIGIBLE", expected_status=422)


# ─── rbac section ───────────────────────────────────────────────────────────────
def test_owner_cannot_create_trainer(api):
    """PRD §2.1: "When a syntactically valid caller attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`." PRD §4:
    "POST | `/trainers` | Create a Trainer | AdminManager".

    Design: Corner/rbac/owner_cannot_create_trainer
    """
    owner = create_owner()
    res = api.create_trainer(create_trainer_payload(full_name="Hack T"),
                             make_owner_headers(owner["id"]))
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS", expected_status=403)


def test_non_assigned_trainer_cannot_start_session(api):
    """PRD §3.8: "Starting a session moves it `SCHEDULED → IN_PROGRESS`; it is permitted only
    when the owning series is `OPEN` (otherwise `ERR_SERIES_NOT_OPEN`) and only for the trainer
    recorded as the session's `trainer_id` (otherwise `ERR_NOT_SESSION_TRAINER`)."

    Design: Corner/rbac/non_assigned_trainer_cannot_start_session
    """
    set_clock()
    trainerA = create_trainer(certified_levels=["BASIC"], full_name="TA")
    trainerB = create_trainer(certified_levels=["BASIC"], full_name="TB")
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    sess = create_session(series, trainerA, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    open_series(series)
    res = api.start_class_session(sess["id"], make_trainer_headers(trainerB["id"]))
    validate_error(res, "ERR_NOT_SESSION_TRAINER", expected_status=403)


def test_owner_cannot_withdraw_another_owners_enrollment(api):
    """PRD §3.6: "An owner (or `FrontDesk` or `AdminManager` on their behalf) withdraws an
    enrollment... The acting owner must own the enrolled dog, or it is rejected with
    `ERR_NOT_DOG_OWNER`."

    Design: Corner/rbac/owner_cannot_withdraw_another_owners_enrollment
    """
    set_clock()
    ownerA = create_owner()
    ownerB = create_owner()
    dog = create_dog(ownerA, name="DA")
    vaccinate_fully(ownerA, dog)
    trainer = create_trainer(certified_levels=["BASIC"])
    series = create_series_draft(level="BASIC", modality="GROUP", capacity=5, session_count=1)
    create_session(series, trainer, 1, "2026-07-01T09:00:00Z", "2026-07-01T10:00:00Z")
    series = open_series(series)
    enr = enroll(ownerA, dog, series, series_version=series["version"])

    res = api.withdraw_enrollment(enr["id"], make_owner_headers(ownerB["id"]))
    validate_error(res, "ERR_NOT_DOG_OWNER", expected_status=403)
