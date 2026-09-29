"""What the server writes for itself: seeded counters, declared defaults, fields taken
from the path or the acting header, and values derived at creation.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client, factories, fixtures
from test_helpers.assertions import (
    assert_attendance_entry,
    assert_enrollment,
    assert_exam_session,
    assert_hours_value,
    assert_proctor,
    assert_section_seats_conserved,
    assert_student,
    assert_testing_room,
)
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
)
from test_helpers.types import (
    AttendanceStatus,
    CenterDecision,
    CredentialStanding,
    EnrollmentStatus,
    IntakeStatus,
    ProctorCertificationStatus,
    ProgramTrack,
    RoomStatus,
    SectionStatus,
    SessionStatus,
    Subtest,
)

ORIENTATION_INSTANT = "2026-08-02T08:00:00Z"
PRE_TEST_AT = "2026-08-02T09:00:00Z"
ATTENDANCE_CLOCK = "2026-08-03T00:00:00Z"
ATTENDANCE_DATE = "2026-08-03"

THREE_HOUR_SITTING = ("2026-08-05T09:00:00Z", "2026-08-05T12:00:00Z")
THREE_AND_A_HALF_HOUR_SITTING = ("2026-08-06T09:00:00Z", "2026-08-06T12:30:00Z")

DEFAULT_SESSION_FORMATS = ["STANDARD", "EXTRA_TIME"]


def test_01_intake_seeds_every_counter_at_zero():
    """"Everything else on a new learner record is server-assigned: `intake_status` begins at
    `INTAKE_STARTED`, `orientation_completed_at` and `placement_efl_level` are null,
    `total_instructional_hours` is 0, `voucher_granted_cents`, `voucher_balance_cents`,
    `voucher_spent_cents`, `exam_fee_owed_cents` and `active_enrollment_count` are all 0, and
    `credential_status` is `NONE`."

    Design: Corner/entities/student_creation_returns_intake_defaults
    """
    created = validate_success(
        api_client.create_student(
            factories.create_student_payload(
                full_name="Amara Vidal",
                email="amara.vidal@example.org",
                primary_track=ProgramTrack.HSE_PREP,
            ),
            headers=make_program_coordinator_headers(),
        ),
        expected_status=201,
    )

    assert_student(created)
    assert created["full_name"] == "Amara Vidal"
    assert created["email"] == "amara.vidal@example.org"
    assert created["primary_track"] == ProgramTrack.HSE_PREP
    assert created["intake_status"] == IntakeStatus.INTAKE_STARTED
    assert created["orientation_completed_at"] is None
    assert created["placement_efl_level"] is None
    assert float(created["total_instructional_hours"]) == 0
    assert created["voucher_granted_cents"] == 0
    assert created["voucher_balance_cents"] == 0
    assert created["voucher_spent_cents"] == 0
    assert created["exam_fee_owed_cents"] == 0
    assert created["credential_status"] == CredentialStanding.NONE
    assert created["active_enrollment_count"] == 0


def test_02_orientation_stamps_the_logical_clock_and_the_read_echoes_it():
    """"Recording orientation completion — an action available to a `Registrar` or a
    `ProgramCoordinator` — moves `intake_status` from `INTAKE_STARTED` to `ORIENTED`, stamps
    `orientation_completed_at` with the logical clock's current instant, and increases the
    learner's `version` by one."

    Design: Corner/entities/student_retrieval_returns_stored_intake_fields
    """
    student = fixtures.create_student(
        full_name="Bea Rowan", email="bea.rowan@example.org", primary_track=ProgramTrack.ESL
    )
    fixtures.set_clock(ORIENTATION_INSTANT)
    validate_success(
        api_client.complete_orientation(student["id"], headers=make_registrar_headers())
    )

    stored = fixtures.read_student(student["id"])
    assert stored["id"] == student["id"]
    assert stored["primary_track"] == ProgramTrack.ESL
    assert stored["intake_status"] == IntakeStatus.ORIENTED
    assert stored["orientation_completed_at"] == ORIENTATION_INSTANT


def test_03_self_pay_authorization_is_false_when_intake_omits_it():
    """"Intake may optionally set `self_pay_authorized`, the flag stating whether the learner
    is permitted to owe an out-of-pocket exam balance; when omitted it is `false`."

    Design: Corner/entities/student_self_pay_authorized_defaults_to_false
    """
    created = validate_success(
        api_client.create_student(
            factories.create_student_payload(
                full_name="Gita Roy", email="gita.roy@example.org"
            ),
            headers=make_program_coordinator_headers(),
        ),
        expected_status=201,
    )
    assert created["self_pay_authorized"] is False
    assert fixtures.read_student(created["id"])["self_pay_authorized"] is False


def test_04_a_room_without_a_buffer_takes_forty_five_minutes_and_starts_active():
    """"A room declares a `room_code`, unique within its centre, a `seat_capacity` between 1
    and 200 inclusive, and optionally a `turnaround_buffer_minutes` — the mandatory clean-down
    gap the room needs between two sittings — which defaults to 45 and must fall between 0
    and 120 inclusive." and "A new room is stored with `status` `ACTIVE` and `service_note`
    null"

    Design: Corner/entities/testing_room_turnaround_buffer_defaults_to_forty_five
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Riverbend HSE Center", state_code="OR"
    )
    room = fixtures.create_room(center["id"], room_code="R-101", seat_capacity=20)

    assert_testing_room(room)
    assert room["turnaround_buffer_minutes"] == 45
    assert room["status"] == RoomStatus.ACTIVE
    assert room["seat_capacity"] == 20
    assert room["service_note"] is None
    assert room["testing_center_id"] == center["id"]


def test_05_a_sitting_defaults_to_draft_with_the_two_ordinary_formats():
    """"It may also declare `supported_formats`, the alternate testing formats the sitting is
    equipped to deliver, drawn from `STANDARD`, `EXTRA_TIME`, `LARGE_PRINT`, `BRAILLE` and
    `AUDIO`; when omitted it defaults to `STANDARD` and `EXTRA_TIME` only" and "A newly
    created sitting is stored with `status` `DRAFT`, `proctor_id` null, `seats_taken` at 0 and
    `cancel_reason` null."

    Design: Corner/entities/exam_session_defaults_draft_without_proctor_and_standard_formats
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Lakeside HSE Center", state_code="WA"
    )
    room = fixtures.create_room(
        center["id"], room_code="R-201", seat_capacity=20, turnaround_buffer_minutes=45
    )

    session = fixtures.create_session(
        center["id"],
        room["id"],
        THREE_HOUR_SITTING[0],
        THREE_HOUR_SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=5,
    )

    assert_exam_session(session)
    assert session["status"] == SessionStatus.DRAFT
    assert session["proctor_id"] is None
    assert session["seats_taken"] == 0
    assert session["cancel_reason"] is None
    assert session["supported_formats"] == DEFAULT_SESSION_FORMATS
    assert session["seat_capacity"] == 5
    assert float(session["duration_hours"]) == 3.00


def test_06_a_proctor_without_a_cap_takes_eight_hours_and_starts_pending():
    """"A **proctor** is registered at a centre by that centre's `CenterAdministrator` or by
    a `StateAuthority`, with the proctor's `full_name` and an optional `daily_hour_cap` — the
    maximum proctored session hours the individual may cover in one UTC calendar day — which
    defaults to 8.00" and "A new proctor begins with `certification_status` `PENDING`,
    `certification_expires_at` null and `assigned_session_count` at 0."

    Design: Corner/entities/proctor_daily_hour_cap_defaults_to_eight_hours
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Northgate HSE Center", state_code="ID"
    )

    proctor = fixtures.create_proctor(center["id"], full_name="Hana Ipsen")

    assert_proctor(proctor)
    assert float(proctor["daily_hour_cap"]) == 8.00
    assert proctor["certification_status"] == ProctorCertificationStatus.PENDING
    assert proctor["certification_expires_at"] is None
    assert proctor["assigned_session_count"] == 0
    assert proctor["testing_center_id"] == center["id"]


def test_07_seat_capacity_is_capped_by_the_room_and_the_span_is_derived():
    """"Its `seat_capacity` is the smaller of the `requested_seats` asked for and the room's
    own `seat_capacity`, so a centre cannot oversell a room by asking for more seats than it
    has. Its `duration_hours` is the span from `starts_at` to `ends_at` expressed in hours to
    two decimal places, rounded half up."

    Design: Corner/entities/exam_session_seat_capacity_and_duration_computed
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Cedar Vale HSE Center", state_code="MT"
    )
    room = fixtures.create_room(
        center["id"], room_code="R-301", seat_capacity=20, turnaround_buffer_minutes=45
    )

    session = fixtures.create_session(
        center["id"],
        room["id"],
        THREE_AND_A_HALF_HOUR_SITTING[0],
        THREE_AND_A_HALF_HOUR_SITTING[1],
        subtest=Subtest.RLA,
        requested_seats=30,
    )
    assert session["requested_seats"] == 30
    assert session["seat_capacity"] == 20
    assert float(session["duration_hours"]) == 3.50

    reread = fixtures.read_session(session["id"])
    assert reread["seat_capacity"] == 20
    assert float(reread["duration_hours"]) == 3.50


def test_08_enrollment_freezes_the_placement_level_and_turns_one_seat():
    """"An accepted enrollment is stored with `status` `ACTIVE`, `posted_hours` at 0,
    `post_test_eligible` false, `withdrawn_at` and `exit_reason` null, and `entry_efl_level`
    frozen as a copy of the learner's `placement_efl_level` at the moment of creation." and
    "Creation also increments the section's `seats_taken` and recomputes `seats_available`,
    increments the learner's `active_enrollment_count`, and — when the learner was `PLACED` —
    advances `intake_status` to `ENROLLED`."

    Design: Corner/entities/enrollment_entry_efl_level_frozen_from_placement
    """
    placed = fixtures.create_placed_student(scale_score=205, pre_test_at=PRE_TEST_AT)
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=ProgramTrack.HSE_PREP,
        title="HSE Morning",
        seats_total=20,
        weekly_hours=6.00,
    )

    enrollment = fixtures.enroll(placed["student_id"], section["id"])

    assert_enrollment(enrollment)
    assert enrollment["entry_efl_level"] == 2
    assert enrollment["status"] == EnrollmentStatus.ACTIVE
    assert float(enrollment["posted_hours"]) == 0
    assert enrollment["post_test_eligible"] is False
    assert enrollment["withdrawn_at"] is None
    assert enrollment["exit_reason"] is None

    stored_section = fixtures.read_class_section(section["id"])
    assert_section_seats_conserved(stored_section)
    assert stored_section["seats_taken"] == 1
    assert stored_section["seats_available"] == 19

    learner = fixtures.read_student(placed["student_id"])
    assert learner["intake_status"] == IntakeStatus.ENROLLED
    assert learner["active_enrollment_count"] == 1


def test_09_a_posted_entry_records_the_keying_user_from_the_header():
    """"Each new entry is stored with `status` `POSTED`, `void_reason` null, and
    `posted_by_user_id` set from the acting `X-User-ID`, which is how the ledger records who
    keyed the hours."

    Design: Corner/entities/attendance_entry_posted_by_user_id_stamped_from_header
    """
    placed = fixtures.create_placed_student(scale_score=205, pre_test_at=PRE_TEST_AT)
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        title="HSE Afternoon",
        instructor_user_id="instructor-7",
        seats_total=10,
        weekly_hours=6.00,
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    fixtures.ensure_clock(ATTENDANCE_CLOCK)

    entry = validate_success(
        api_client.create_attendance_entry(
            enrollment["id"],
            factories.create_attendance_entry_payload(ATTENDANCE_DATE, 2.50),
            headers=make_instructor_headers("instructor-7"),
        ),
        expected_status=201,
    )

    assert_attendance_entry(entry)
    assert entry["posted_by_user_id"] == "instructor-7"
    assert entry["enrollment_id"] == enrollment["id"]
    assert entry["status"] == AttendanceStatus.POSTED
    assert entry["void_reason"] is None
    assert_hours_value(entry["hours"], 2.50)
    assert entry["attendance_date"] == ATTENDANCE_DATE

    stored = fixtures.read_enrollment(enrollment["id"])
    assert_hours_value(stored["posted_hours"], 2.50)
    assert stored["post_test_eligible"] is False
