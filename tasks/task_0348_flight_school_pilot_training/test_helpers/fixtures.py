"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a specific state reached
through 5-20 API calls (an ACTIVE enrollment over a funded student, a dispatched
booking, a posted flight log, a grounded aircraft, etc). These helpers
encapsulate those sequences so tests focus on assertions.

Identity threading (mandatory): Student and Instructor are entity-backed roles.
After creating a Student/Instructor, every ownership-gated call (flight-log
post, stage checks, endorsement issue/revoke, a student requesting their own
booking) uses make_student_headers(stu_id) / make_instructor_headers(instr_id)
with the ACTUAL entity id — never the shared TEST_USERS fallback. Opaque roles
(SchoolAdmin, Dispatcher, Mechanic) use the shared constants.

All helpers use get_success_data() (lenient) so setup failures surface as clear
"setup failed" errors rather than confusing assertion failures.

The harness restarts the server (empty DB) before every test, so each helper
builds its whole world from scratch.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_student_payload,
    create_instructor_payload,
    create_aircraft_payload,
    create_syllabus_payload,
    create_enrollment_payload,
    create_deposit_payload,
    create_squawk_payload,
    create_clearance_payload,
    create_booking_payload,
    create_flight_log_payload,
    create_stage_check_payload,
    create_endorsement_payload,
)
from .test_users import (
    TEST_USERS,
    make_student_headers,
    make_instructor_headers,
)

ADMIN = TEST_USERS["school_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
MECHANIC = TEST_USERS["mechanic_headers"]

# Stable future window helpers (UTC, ISO 8601 with ms). Distinct windows avoid
# accidental aircraft-time conflicts unless a test deliberately overlaps them.
WIN_A = ("2026-07-01T14:00:00.000Z", "2026-07-01T16:00:00.000Z")
WIN_B = ("2026-07-02T14:00:00.000Z", "2026-07-02T16:00:00.000Z")
WIN_C = ("2026-07-03T14:00:00.000Z", "2026-07-03T16:00:00.000Z")
MEDICAL_EXPIRY = "2027-06-14T00:00:00.000Z"


# ──────────────────────────────────────────────────────────────────────────
# Tier 0: primitives
# ──────────────────────────────────────────────────────────────────────────
def create_student(deposit_cents=0, **overrides) -> dict:
    """Create a student; optionally fund it with a single block-time deposit."""
    stu = get_success_data(api_client.create_student(create_student_payload(**overrides), ADMIN))
    if deposit_cents:
        api_client.create_deposit(stu["id"], create_deposit_payload(deposit_cents), ADMIN)
        stu = get_student(stu["id"])
    return stu


def add_deposit(student_id, amount_cents, **overrides) -> dict:
    return get_success_data(
        api_client.create_deposit(student_id, create_deposit_payload(amount_cents, **overrides), ADMIN)
    )


def create_instructor(**overrides) -> dict:
    return get_success_data(api_client.create_instructor(create_instructor_payload(**overrides), ADMIN))


def create_aircraft(**overrides) -> dict:
    return get_success_data(api_client.create_aircraft(create_aircraft_payload(**overrides), ADMIN))


def create_syllabus(**overrides) -> dict:
    return get_success_data(api_client.create_syllabus(create_syllabus_payload(**overrides), ADMIN))


def create_enrollment(student_id, syllabus_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_enrollment(create_enrollment_payload(student_id, syllabus_id, **overrides), ADMIN)
    )


def get_student(student_id) -> dict:
    return get_success_data(api_client.get_student(student_id, ADMIN))


def get_aircraft(aircraft_id) -> dict:
    return get_success_data(api_client.get_aircraft(aircraft_id, DISPATCHER))


def get_aircraft_version(aircraft_id) -> int:
    return get_aircraft(aircraft_id)["version"]


def get_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, ADMIN))


def get_booking(booking_id) -> dict:
    return get_success_data(api_client.get_booking(booking_id, DISPATCHER))


def get_flight_log(flight_log_id) -> dict:
    return get_success_data(api_client.get_flight_log(flight_log_id, DISPATCHER))


def get_stage_check(stage_check_id) -> dict:
    return get_success_data(api_client.get_stage_check(stage_check_id, ADMIN))


def get_squawk(squawk_id) -> dict:
    return get_success_data(api_client.get_squawk(squawk_id, MECHANIC))


def get_endorsement(endorsement_id) -> dict:
    return get_success_data(api_client.get_endorsement(endorsement_id, ADMIN))


def list_deposit_transactions(student_id) -> list:
    res = api_client.list_deposit_transactions(DISPATCHER, params={"student_id": student_id})
    return get_success_data(res)


def clear_medical(enrollment_id, decision="CLEARED", expiry=MEDICAL_EXPIRY) -> dict:
    payload = create_clearance_payload("MEDICAL", decision)
    if decision == "CLEARED" and expiry is not None:
        payload["medical_expiry_date"] = expiry
    return get_success_data(api_client.record_clearance(enrollment_id, payload, ADMIN))


def clear_tsa(enrollment_id, decision="CLEARED") -> dict:
    return get_success_data(
        api_client.record_clearance(enrollment_id, create_clearance_payload("TSA", decision), ADMIN)
    )


# ──────────────────────────────────────────────────────────────────────────
# Tier 1: enrollment state progression
# ──────────────────────────────────────────────────────────────────────────
def setup_active_enrollment(
    deposit_cents=100000,
    min_deposit_cents=50000,
    syllabus_overrides=None,
    instructor_overrides=None,
):
    """Funded student + syllabus + instructor + ACTIVE enrollment (both axes cleared).

    Returns dict with keys: student, syllabus, instructor, enrollment.
    """
    syllabus_overrides = dict(syllabus_overrides or {})
    syllabus_overrides.setdefault("min_deposit_cents", min_deposit_cents)
    student = create_student(deposit_cents=deposit_cents)
    syllabus = create_syllabus(**syllabus_overrides)
    instructor = create_instructor(**(instructor_overrides or {}))
    enrollment = create_enrollment(student["id"], syllabus["id"])
    clear_medical(enrollment["id"])
    clear_tsa(enrollment["id"])
    api_client.activate_enrollment(enrollment["id"], ADMIN)
    return {
        "student": get_student(student["id"]),
        "syllabus": syllabus,
        "instructor": instructor,
        "enrollment": get_enrollment(enrollment["id"]),
    }


def setup_cleared_pending_enrollment(deposit_cents=60000, min_deposit_cents=50000):
    """Funded student + syllabus + enrollment with BOTH axes cleared but NOT activated.

    Returns dict: student, syllabus, enrollment. Used for activation-gate tests.
    """
    student = create_student(deposit_cents=deposit_cents)
    syllabus = create_syllabus(min_deposit_cents=min_deposit_cents)
    enrollment = create_enrollment(student["id"], syllabus["id"])
    clear_medical(enrollment["id"])
    clear_tsa(enrollment["id"])
    return {
        "student": get_student(student["id"]),
        "syllabus": syllabus,
        "enrollment": get_enrollment(enrollment["id"]),
    }


# ──────────────────────────────────────────────────────────────────────────
# Tier 2: bookings against an active enrollment
# ──────────────────────────────────────────────────────────────────────────
def create_booking(
    enrollment_id, aircraft_id, lesson_type, estimated_hours,
    window=WIN_A, instructor_id=None, headers=None, **overrides,
):
    """Create a REQUESTED booking, reading the live aircraft version for OCC.

    Pass headers to act as a specific principal (e.g. a Student requesting their
    own booking); defaults to Dispatcher.
    """
    start_at, end_at = window
    version = get_aircraft_version(aircraft_id)
    payload = create_booking_payload(
        enrollment_id, aircraft_id, lesson_type, start_at, end_at,
        estimated_hours, version, **overrides,
    )
    if instructor_id is not None:
        payload["instructor_id"] = instructor_id
    return get_success_data(api_client.create_booking(payload, headers or DISPATCHER))


def setup_confirmed_booking(
    deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
    aircraft_overrides=None, instructor_overrides=None, window=WIN_A,
):
    """Active enrollment + a CONFIRMED booking (hold placed).

    Returns dict: student, syllabus, instructor, enrollment, aircraft, booking.
    """
    base = setup_active_enrollment(deposit_cents=deposit_cents, instructor_overrides=instructor_overrides)
    aircraft = create_aircraft(**(aircraft_overrides or {}))
    instr_id = base["instructor"]["id"] if lesson_type == "DUAL" else None
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], lesson_type, estimated_hours,
        window=window, instructor_id=instr_id,
    )
    api_client.confirm_booking(booking["id"], DISPATCHER)
    return {
        **base,
        "student": get_student(base["student"]["id"]),
        "aircraft": get_aircraft(aircraft["id"]),
        "booking": get_booking(booking["id"]),
    }


def setup_dispatched_booking(
    deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
    aircraft_overrides=None, with_solo_endorsement=False, window=WIN_A,
):
    """Active enrollment + a DISPATCHED booking, ready for a flight log.

    For SOLO lessons set with_solo_endorsement=True so dispatch passes the
    endorsement gate. Returns dict including student, instructor, enrollment,
    aircraft, booking.
    """
    base = setup_active_enrollment(deposit_cents=deposit_cents)
    aircraft = create_aircraft(**(aircraft_overrides or {}))
    instr_id = base["instructor"]["id"] if lesson_type == "DUAL" else None
    if lesson_type == "SOLO" and with_solo_endorsement:
        issue_endorsement(base["enrollment"]["id"], base["instructor"]["id"], "SOLO")
    booking = create_booking(
        base["enrollment"]["id"], aircraft["id"], lesson_type, estimated_hours,
        window=window, instructor_id=instr_id,
    )
    api_client.confirm_booking(booking["id"], DISPATCHER)
    api_client.dispatch_booking(booking["id"], DISPATCHER)
    return {
        **base,
        "student": get_student(base["student"]["id"]),
        "aircraft": get_aircraft(aircraft["id"]),
        "booking": get_booking(booking["id"]),
    }


# ──────────────────────────────────────────────────────────────────────────
# Tier 3: flight logs
# ──────────────────────────────────────────────────────────────────────────
def create_draft_flight_log(booking_id, instructor_id, hobbs_start, hobbs_end,
                            tach_start, tach_end, landings=1):
    """Create a DRAFT flight log. instructor_id drives the entity-backed header."""
    payload = create_flight_log_payload(booking_id, hobbs_start, hobbs_end, tach_start, tach_end, landings)
    return get_success_data(
        api_client.create_flight_log(payload, make_instructor_headers(instructor_id))
    )


def setup_drafted_flight_log(
    deposit_cents=100000, estimated_hours=2.0, lesson_type="DUAL",
    aircraft_overrides=None, hobbs_start=100.0, hobbs_end=101.7,
    tach_start=200.0, tach_end=201.4, landings=1, with_solo_endorsement=False,
):
    """Dispatched booking + a DRAFT flight log, ready to post or void.

    Returns dict including flight_log plus everything from setup_dispatched_booking.
    """
    base = setup_dispatched_booking(
        deposit_cents=deposit_cents, estimated_hours=estimated_hours, lesson_type=lesson_type,
        aircraft_overrides=aircraft_overrides, with_solo_endorsement=with_solo_endorsement,
    )
    flight_log = create_draft_flight_log(
        base["booking"]["id"], base["instructor"]["id"],
        hobbs_start, hobbs_end, tach_start, tach_end, landings,
    )
    return {**base, "flight_log": flight_log}


# ──────────────────────────────────────────────────────────────────────────
# Tier 4: squawks / aircraft grounding
# ──────────────────────────────────────────────────────────────────────────
def report_squawk(aircraft_id, is_grounding, **overrides):
    return get_success_data(
        api_client.create_squawk(create_squawk_payload(aircraft_id, is_grounding, **overrides), MECHANIC)
    )


def setup_grounded_aircraft(**aircraft_overrides):
    """Aircraft grounded by one OPEN grounding squawk.

    Returns dict: aircraft (re-read, GROUNDED), squawk.
    """
    aircraft = create_aircraft(**aircraft_overrides)
    squawk = report_squawk(aircraft["id"], True)
    return {"aircraft": get_aircraft(aircraft["id"]), "squawk": get_squawk(squawk["id"])}


# ──────────────────────────────────────────────────────────────────────────
# Tier 5: stage checks
# ──────────────────────────────────────────────────────────────────────────
def schedule_stage_check(enrollment_id, examiner_instructor_id, stage_index, **overrides):
    payload = create_stage_check_payload(enrollment_id, examiner_instructor_id, stage_index, **overrides)
    return get_success_data(api_client.create_stage_check(payload, ADMIN))


def setup_failed_stage_check(stage_index=1):
    """Active enrollment + a stage check driven SCHEDULED->IN_PROGRESS->FAILED.

    Returns dict: student, syllabus, instructor, enrollment, stage_check (FAILED).
    """
    base = setup_active_enrollment(deposit_cents=60000)
    sc = schedule_stage_check(base["enrollment"]["id"], base["instructor"]["id"], stage_index)
    instr_headers = make_instructor_headers(base["instructor"]["id"])
    api_client.begin_stage_check(sc["id"], instr_headers)
    api_client.fail_stage_check(sc["id"], instr_headers, {"result_note": "Unsatisfactory"})
    return {**base, "stage_check": get_stage_check(sc["id"])}


def setup_passed_stage_check(stage_index=1):
    """Active enrollment + a PASSED stage check (terminal).

    Returns dict: student, syllabus, instructor, enrollment, stage_check (PASSED).
    """
    base = setup_active_enrollment(deposit_cents=60000)
    sc = schedule_stage_check(base["enrollment"]["id"], base["instructor"]["id"], stage_index)
    instr_headers = make_instructor_headers(base["instructor"]["id"])
    api_client.begin_stage_check(sc["id"], instr_headers)
    api_client.pass_stage_check(sc["id"], instr_headers)
    return {
        **base,
        "enrollment": get_enrollment(base["enrollment"]["id"]),
        "stage_check": get_stage_check(sc["id"]),
    }


# ──────────────────────────────────────────────────────────────────────────
# Tier 6: endorsements
# ──────────────────────────────────────────────────────────────────────────
def issue_endorsement(enrollment_id, instructor_id, endorsement_code):
    payload = create_endorsement_payload(enrollment_id, instructor_id, endorsement_code)
    return get_success_data(
        api_client.create_endorsement(payload, make_instructor_headers(instructor_id))
    )
