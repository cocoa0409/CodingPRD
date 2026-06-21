"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test). These helpers build multi-step preconditions from scratch
using only PRD-declared endpoints, then return the created resources so tests
can focus on assertions.

Setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup failed" rather than a confusing
assertion mismatch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_instructor_headers,
    make_student_headers,
    make_guardian_headers,
)
from .factories import (
    create_course_package_payload,
    create_student_payload,
    create_guardian_consent_payload,
    create_enrollment_payload,
    create_instructor_payload,
    create_vehicle_payload,
    create_lesson_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# Clock control
# ===========================================================================
def set_clock(iso: str):
    """Set the server clock to an ISO 8601 instant (§3.11)."""
    return get_success_data(api_client.set_clock(iso, ADMIN))


# ===========================================================================
# Tier 0: single-resource creation (return the created entity dict)
# ===========================================================================
def create_package(**overrides) -> dict:
    return get_success_data(
        api_client.create_course_package(create_course_package_payload(**overrides), ADMIN)
    )


def create_student(**overrides) -> dict:
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), ADMIN)
    )


def create_instructor(**overrides) -> dict:
    return get_success_data(
        api_client.create_instructor(create_instructor_payload(**overrides), ADMIN)
    )


def create_vehicle(**overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(create_vehicle_payload(**overrides), ADMIN)
    )


def create_enrollment(student_id: str, package_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(student_id, package_id, **overrides), ADMIN
        )
    )


def create_granted_consent(student_id: str, **overrides) -> dict:
    """Create a guardian consent and move it PENDING -> GRANTED.
    Identity threading: grant is performed AS the guardian (consent id)."""
    consent = get_success_data(
        api_client.create_guardian_consent(
            create_guardian_consent_payload(student_id, **overrides), ADMIN
        )
    )
    get_success_data(
        api_client.grant_consent(consent["id"], make_guardian_headers(consent["id"]))
    )
    return consent


# ===========================================================================
# Helpers for the OCC version dance
# ===========================================================================
def student_version(student_id: str) -> int:
    """Read the live Student.version (the value POST /lessons must carry as
    expected_student_version, §2.10)."""
    stu = get_success_data(api_client.get_student(student_id, ADMIN))
    return stu["version"]


# ===========================================================================
# Tier 1: state progression
# ===========================================================================
def create_active_enrollment(student_id: str, package_id: str, **overrides) -> dict:
    """Create a DRAFT enrollment and activate it (DRAFT -> ACTIVE)."""
    enr = create_enrollment(student_id, package_id, **overrides)
    return get_success_data(api_client.activate_enrollment(enr["id"], ADMIN))


def create_permitted_student(package=None, **student_overrides) -> dict:
    """Return a dict {student, package, enrollment} for an adult student whose
    enrollment is ACTIVE and who is PERMITTED (permit recorded).

    Reaches: PROSPECT -> (activate bubbles) ENROLLED -> (record-permit) PERMITTED.
    """
    pkg = package or create_package(
        included_classroom_hours=0, included_online_hours=0,
        included_road_hours=6, enrollment_fee_cents=0, bundle_discount_cents=0,
    )
    stu = create_student(**student_overrides)
    enr = create_active_enrollment(stu["id"], pkg["id"])
    get_success_data(
        api_client.record_permit(stu["id"], {"permit_number": "P-AUTO"}, ADMIN)
    )
    stu = get_success_data(api_client.get_student(stu["id"], ADMIN))
    return {"student": stu, "package": pkg, "enrollment": enr}


# ===========================================================================
# Tier 2: entity hierarchy — road-ready scheduling contexts
# ===========================================================================
def setup_road_scheduling_context(
    package_overrides=None, instructor_overrides=None,
    vehicle_overrides=None, student_overrides=None, grant_consent=False,
):
    """Active enrollment + certified instructor + dual-control vehicle, with a
    PERMITTED student ready to have a ROAD lesson scheduled. Returns a dict.

    If grant_consent is True a GRANTED guardian consent is also created (for
    minor students). Returns student/package/enrollment/instructor/vehicle and,
    when applicable, consent.
    """
    pkg = create_package(**(package_overrides or {
        "included_classroom_hours": 0, "included_online_hours": 0,
        "included_road_hours": 6, "enrollment_fee_cents": 0,
        "bundle_discount_cents": 0,
    }))
    inst = create_instructor(**(instructor_overrides or {"certified_road": True}))
    veh = create_vehicle(**(vehicle_overrides or {"dual_control": True}))
    stu = create_student(**(student_overrides or {}))

    consent = None
    if grant_consent:
        consent = create_granted_consent(stu["id"])

    enr = create_active_enrollment(stu["id"], pkg["id"])
    get_success_data(
        api_client.record_permit(stu["id"], {"permit_number": "P-AUTO"}, ADMIN)
    )
    stu = get_success_data(api_client.get_student(stu["id"], ADMIN))
    out = {
        "student": stu, "package": pkg, "enrollment": enr,
        "instructor": inst, "vehicle": veh,
    }
    if consent is not None:
        out["consent"] = consent
    return out


def setup_classroom_scheduling_context(
    package_overrides=None, instructor_overrides=None, student_overrides=None,
):
    """Active enrollment + instructor + adult student for CLASSROOM/ONLINE
    lessons (no permit/road prerequisites). Returns a dict."""
    pkg = create_package(**(package_overrides or {
        "included_classroom_hours": 30, "included_online_hours": 8,
        "included_road_hours": 0, "enrollment_fee_cents": 0,
        "bundle_discount_cents": 0,
    }))
    inst = create_instructor(**(instructor_overrides or {"certified_road": False}))
    stu = create_student(**(student_overrides or {}))
    enr = create_active_enrollment(stu["id"], pkg["id"])
    stu = get_success_data(api_client.get_student(stu["id"], ADMIN))
    return {"student": stu, "package": pkg, "enrollment": enr, "instructor": inst}


# ===========================================================================
# Tier 3: lesson lifecycle shortcuts
# ===========================================================================
def schedule_lesson(student_id, enrollment_id, lesson_type, start_at, end_at,
                    instructor_id=None, vehicle_id=None, expected_version=None):
    """Schedule one lesson, threading the live student version automatically
    when expected_version is not supplied. Returns the created Lesson."""
    if expected_version is None:
        expected_version = student_version(student_id)
    extra = {}
    if instructor_id is not None:
        extra["instructor_id"] = instructor_id
    if vehicle_id is not None:
        extra["vehicle_id"] = vehicle_id
    payload = create_lesson_payload(
        student_id, enrollment_id, lesson_type, start_at, end_at,
        expected_version, **extra,
    )
    return get_success_data(api_client.create_lesson(payload, ADMIN))


def complete_lesson_at(lesson_id, instructor_id, clock_iso):
    """Advance the clock to clock_iso then complete the lesson as its
    instructor (identity-threaded). Returns the completed Lesson."""
    set_clock(clock_iso)
    return get_success_data(
        api_client.complete_lesson(lesson_id, make_instructor_headers(instructor_id))
    )


def schedule_and_complete(student_id, enrollment_id, lesson_type, start_at, end_at,
                          instructor_id, complete_clock, vehicle_id=None):
    """Schedule one lesson and immediately complete it after its end. Returns
    the completed Lesson. Handles version threading and clock advance."""
    lesson = schedule_lesson(
        student_id, enrollment_id, lesson_type, start_at, end_at,
        instructor_id=instructor_id, vehicle_id=vehicle_id,
    )
    return complete_lesson_at(lesson["id"], instructor_id, complete_clock)


# ===========================================================================
# Tier 4: accumulation / threshold targeting
# ===========================================================================
def setup_student_at_full_readiness(start_clock="2026-06-01T00:00:00.000Z"):
    """Build a ROAD_READY student whose readiness_score == 1.0 (road 6,
    classroom 30, online 8 all completed) on a both-tracks package.

    Returns dict: student, package, enrollment, instructor, vehicle.
    Leaves the clock at the final completion instant.
    """
    set_clock(start_clock)
    ctx = setup_road_scheduling_context(package_overrides={
        "included_classroom_hours": 30, "included_online_hours": 8,
        "included_road_hours": 6, "enrollment_fee_cents": 5000,
        "bundle_discount_cents": 5000, "price_cents": 90000,
    })
    stu, enr = ctx["student"], ctx["enrollment"]
    inst, veh = ctx["instructor"], ctx["vehicle"]

    # 30h classroom in one lesson (2026-06-02 08:00 -> 2026-06-03 14:00 = 30h)
    schedule_and_complete(
        stu["id"], enr["id"], "CLASSROOM",
        "2026-06-02T08:00:00.000Z", "2026-06-03T14:00:00.000Z",
        inst["id"], "2026-06-03T14:00:00.000Z",
    )
    # 8h online (2026-06-04 08:00 -> 16:00 = 8h)
    schedule_and_complete(
        stu["id"], enr["id"], "ONLINE",
        "2026-06-04T08:00:00.000Z", "2026-06-04T16:00:00.000Z",
        inst["id"], "2026-06-04T16:00:00.000Z",
    )
    # 6h road (2026-06-05 08:00 -> 14:00 = 6h) -> bubbles PERMITTED -> ROAD_READY
    schedule_and_complete(
        stu["id"], enr["id"], "ROAD",
        "2026-06-05T08:00:00.000Z", "2026-06-05T14:00:00.000Z",
        inst["id"], "2026-06-05T14:00:00.000Z", vehicle_id=veh["id"],
    )
    stu = get_success_data(api_client.get_student(stu["id"], ADMIN))
    ctx["student"] = stu
    return ctx


# ===========================================================================
# Tier 5: finalization / terminal state — certificate & licensure
# ===========================================================================
def setup_issued_certificate(start_clock="2026-06-01T00:00:00.000Z"):
    """Full path to a ROAD_READY student with an ISSUED Certificate.
    Returns dict: student, package, enrollment, instructor, vehicle, certificate.
    """
    ctx = setup_student_at_full_readiness(start_clock)
    cert = get_success_data(
        api_client.issue_certificate(
            ctx["student"]["id"], {"enrollment_id": ctx["enrollment"]["id"]}, ADMIN
        )
    )
    ctx["certificate"] = cert
    ctx["student"] = get_success_data(
        api_client.get_student(ctx["student"]["id"], ADMIN)
    )
    return ctx


def setup_submitted_certificate(start_clock="2026-06-01T00:00:00.000Z"):
    """ROAD_READY/CERTIFIED student with a SUBMITTED certificate.
    Returns dict including certificate (SUBMITTED)."""
    ctx = setup_issued_certificate(start_clock)
    cert = get_success_data(
        api_client.submit_certificate(ctx["certificate"]["id"], ADMIN)
    )
    ctx["certificate"] = cert
    return ctx


def setup_licensed_student(start_clock="2026-06-01T00:00:00.000Z"):
    """Drive a student all the way to LICENSED (certificate ACCEPTED).
    Returns dict including certificate (ACCEPTED) and the LICENSED student."""
    ctx = setup_submitted_certificate(start_clock)
    cert = get_success_data(
        api_client.dmv_callback(
            ctx["certificate"]["id"], {"outcome": "ACCEPTED"}, ADMIN
        )
    )
    ctx["certificate"] = cert
    ctx["student"] = get_success_data(
        api_client.get_student(ctx["student"]["id"], ADMIN)
    )
    return ctx
