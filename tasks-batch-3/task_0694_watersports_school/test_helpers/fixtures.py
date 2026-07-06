"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient 2xx validator) for setup calls so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion failure deep in a test.

Every fixture rebuilds its world from scratch: the harness restarts the server
(empty DB, clock at the 2026-03-01T00:00:00Z default) before each test, so no
state carries across tests.

Identity threading: SchoolAdmin is opaque and is used for all administrative
setup. Where an entity-backed (Instructor / Student) ownership-gated call is
needed, the helper threads the real entity id via make_instructor_headers /
make_student_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_school_payload, create_course_payload, create_level_payload,
    create_instructor_payload, create_equipment_payload, create_student_payload,
    create_waiver_payload, create_membership_payload, create_enrollment_payload,
    create_session_payload, create_booking_payload, create_rental_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]


# ─── Clock control ──────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Move the logical clock. Returns the resulting current_utc."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: primitive creators (each returns the created entity dict) ───────
def create_school(**overrides):
    return get_success_data(api_client.create_school(create_school_payload(**overrides), ADMIN))


def create_course(school_id, **overrides):
    return get_success_data(
        api_client.create_course(create_course_payload(school_id, **overrides), ADMIN))


def create_level(course_id, **overrides):
    return get_success_data(
        api_client.create_level(create_level_payload(course_id, **overrides), ADMIN))


def create_instructor(school_id, **overrides):
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(school_id, **overrides), ADMIN))


def create_equipment(school_id, **overrides):
    return get_success_data(
        api_client.create_equipment(create_equipment_payload(school_id, **overrides), ADMIN))


def create_student(school_id, **overrides):
    return get_success_data(
        api_client.create_student(create_student_payload(school_id, **overrides), ADMIN))


def create_waiver(student_id, **overrides):
    return get_success_data(
        api_client.create_waiver(create_waiver_payload(student_id, **overrides), ADMIN))


def create_membership(student_id, **overrides):
    return get_success_data(
        api_client.create_membership(create_membership_payload(student_id, **overrides), ADMIN))


def create_student_with_waiver(school_id, waiver_overrides=None, **student_overrides):
    """Register a student and sign a SIGNED waiver. Returns the student dict
    (its waiver_status becomes SIGNED via the cross-entity recompute)."""
    student = create_student(school_id, **student_overrides)
    create_waiver(student["id"], **(waiver_overrides or {}))
    return student


# ─── Tier 2: catalog setup ───────────────────────────────────────────────────
def setup_catalog(level_overrides=None, course_overrides=None,
                  instructor_overrides=None, school_overrides=None):
    """Active OPEN school + course + one level + one certified instructor.

    Returns dict: {school, course, level, instructor}. The instructor is
    certified for the course discipline so session scheduling passes that gate.
    """
    school = create_school(**(school_overrides or {}))
    course = create_course(school["id"], **(course_overrides or {}))
    level = create_level(course["id"], **(level_overrides or {}))
    inst_overrides = dict(instructor_overrides or {})
    # Default instructor certification to the course discipline.
    inst_overrides.setdefault("certified_disciplines", [course["discipline"]])
    instructor = create_instructor(school["id"], **inst_overrides)
    return {"school": school, "course": course, "level": level, "instructor": instructor}


# ─── Tier 3: enrollment helpers ──────────────────────────────────────────────
def create_enrollment(school_id, student_id, course_level_id, **overrides):
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(school_id, student_id, course_level_id, **overrides), ADMIN))


def create_paid_enrollment(school_id, student_id, course_level_id, **overrides):
    """Create an enrollment and drive payment_status to PAID."""
    enr = create_enrollment(school_id, student_id, course_level_id, **overrides)
    get_success_data(api_client.pay_enrollment(enr["id"], ADMIN))
    return get_success_data(api_client.get_enrollment(enr["id"], ADMIN))


def create_paid_withdrawn_enrollment(school_id, student_id, course_level_id, **overrides):
    """Create -> pay -> withdraw. Returns the enrollment after withdrawal."""
    enr = create_enrollment(school_id, student_id, course_level_id, **overrides)
    get_success_data(api_client.pay_enrollment(enr["id"], ADMIN))
    get_success_data(api_client.withdraw_enrollment(enr["id"], ADMIN))
    return get_success_data(api_client.get_enrollment(enr["id"], ADMIN))


# ─── Tier 4: session + booking helpers ───────────────────────────────────────
def create_session(school_id, course_level_id, instructor_id, **overrides):
    return get_success_data(api_client.create_session(
        create_session_payload(school_id, course_level_id, instructor_id, **overrides), ADMIN))


def book(session_id, enrollment_id, expected_session_version, **overrides):
    """Create a booking against a session, threading the OCC version.
    Returns the booking dict."""
    return get_success_data(api_client.create_booking(
        create_booking_payload(session_id, enrollment_id, expected_session_version, **overrides),
        ADMIN))


def book_fresh(session_id, enrollment_id, **overrides):
    """Read the session's live version then create a booking with it.

    Useful when several bookings are added in sequence to the same session and
    the caller does not want to thread versions manually.
    Returns (booking, new_session_version).
    """
    sess = get_success_data(api_client.get_session(session_id, ADMIN))
    booking = book(session_id, enrollment_id, sess["version"], **overrides)
    refreshed = get_success_data(api_client.get_session(session_id, ADMIN))
    return booking, refreshed["version"]


def attend_session(session_id, booking_ids, start_clock):
    """Drive a session through start -> (check-in each booking) -> complete.

    Sets the clock to `start_clock` (which must lie inside the session's tide
    window) before starting. Each checked-in booking becomes ATTENDED on
    completion. Returns the completed session dict.
    """
    set_clock(start_clock)
    get_success_data(api_client.start_session(session_id, ADMIN))
    for bk_id in booking_ids:
        get_success_data(api_client.check_in_booking(bk_id, ADMIN))
    return get_success_data(api_client.complete_session(session_id, ADMIN))


# ─── Tier 5: equipment / rental helpers ──────────────────────────────────────
def create_rental(school_id, student_id, equipment_item_id, expected_equipment_version,
                  **overrides):
    return get_success_data(api_client.create_rental(
        create_rental_payload(school_id, student_id, equipment_item_id,
                              expected_equipment_version, **overrides), ADMIN))


def create_reserved_rental(school_id, **rental_overrides):
    """Student + AVAILABLE equipment + one RESERVED rental on it.

    Returns dict: {student, equipment, rental}. Equipment defaults pulled from
    the factory; pass equipment_overrides / rental-window overrides as needed.
    """
    equipment_overrides = rental_overrides.pop("equipment_overrides", {})
    student = create_student(school_id)
    equipment = create_equipment(school_id, **equipment_overrides)
    rental = create_rental(school_id, student["id"], equipment["id"],
                           equipment["version"], **rental_overrides)
    return {"student": student, "equipment": equipment, "rental": rental}


def equipment_version(equipment_id):
    """Read the equipment item's current version (after a mutation bumped it)."""
    return get_success_data(api_client.get_equipment(equipment_id, ADMIN))["version"]


def set_storm_advisory(school_id, active, expected_school_version):
    """Toggle a storm advisory (OCC-guarded). Returns the school dict."""
    return get_success_data(api_client.set_storm_advisory(
        school_id, {"active": active, "expected_school_version": expected_school_version}, ADMIN))


def set_maintenance(equipment_id, in_maintenance, expected_equipment_version):
    """Toggle equipment maintenance (OCC-guarded). Returns the equipment dict."""
    return get_success_data(api_client.toggle_maintenance(
        equipment_id,
        {"in_maintenance": in_maintenance,
         "expected_equipment_version": expected_equipment_version},
        ADMIN))
