"""Edges on the instructional side of the system: the one-way orientation step, the section's
three-step ladder and its settling cascade, withdrawal, and the immutability of a score.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_hours_value, assert_section_seats_conserved
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
)
from test_helpers.types import (
    EnrollmentStatus,
    ExitReason,
    IntakeStatus,
    ProgramTrack,
    SectionStatus,
    TestEventPurpose,
    TestEventStatus,
    TestForm,
)

FIRST_ORIENTATION_INSTANT = "2026-08-04T10:00:00Z"
LATER_CLOCK = "2026-08-06T10:00:00Z"

PRE_TEST_AT = "2026-08-02T09:00:00Z"
RESCORE_CLOCK = "2026-08-03T09:00:00Z"
BOOKED_FOR = "2026-08-09T09:00:00Z"

CASCADE_CLOCK = "2026-08-08T00:00:00Z"
FULL_HOUR_DATES = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07")
DAILY_HOURS = 8.00

WITHDRAW_CLOCK = "2026-08-05T00:00:00Z"
WITHDRAW_REASON = "moved out of state"
FROZEN_LEDGER_REASON = "employment conflict"


def _transition(section_id, target_status):
    return api_client.transition_class_section(
        section_id,
        factories.section_transition_payload(target_status),
        headers=make_program_coordinator_headers(),
    )


def _withdraw(enrollment_id, exit_reason):
    return api_client.withdraw_enrollment(
        enrollment_id,
        factories.withdraw_enrollment_payload(exit_reason),
        headers=make_program_coordinator_headers(),
    )


def _setup_two_learners_on_one_section():
    """Two learners on one OPEN section, one past forty hours and one well short."""
    first = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        full_name="Uma Diallo",
        email="uma.diallo@example.org",
        pre_test_at=PRE_TEST_AT,
    )
    second = fixtures.create_placed_student(
        scale_score=205,
        test_form=TestForm.CASAS_R_900,
        full_name="Viktor Halle",
        email="viktor.halle@example.org",
        pre_test_at=PRE_TEST_AT,
    )
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=ProgramTrack.HSE_PREP,
        title="Conditional Cascade",
        instructor_user_id="instructor-8",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=8.00,
    )
    first_enrollment = fixtures.enroll(first["student_id"], section["id"])
    second_enrollment = fixtures.enroll(second["student_id"], section["id"])

    fixtures.set_clock(CASCADE_CLOCK)
    for date in FULL_HOUR_DATES:
        fixtures.post_attendance(first_enrollment["id"], date, DAILY_HOURS)
    fixtures.post_attendance(second_enrollment["id"], FULL_HOUR_DATES[0], DAILY_HOURS)

    return {
        "section_id": section["id"],
        "full_student_id": first["student_id"],
        "short_student_id": second["student_id"],
        "full_enrollment_id": first_enrollment["id"],
        "short_enrollment_id": second_enrollment["id"],
    }


def _setup_active_enrollment(title, instructor_user_id, full_name, email):
    placed = fixtures.create_placed_student(
        scale_score=205, full_name=full_name, email=email, pre_test_at=PRE_TEST_AT
    )
    section = fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=ProgramTrack.HSE_PREP,
        title=title,
        instructor_user_id=instructor_user_id,
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    return {
        "student_id": placed["student_id"],
        "section_id": section["id"],
        "enrollment_id": enrollment["id"],
    }


def test_01_orientation_moves_the_learner_forward_without_placing_them():
    """"Recording orientation completion — an action available to a `Registrar` or a
    `ProgramCoordinator` — moves `intake_status` from `INTAKE_STARTED` to `ORIENTED`, stamps
    `orientation_completed_at` with the logical clock's current instant, and increases the
    learner's `version` by one. The request carries no payload."

    Design: Corner/state_machines/student_orientation_completion_valid_transition
    """
    student = fixtures.create_student(
        full_name="Pia Renn",
        email="pia.renn@example.org",
        primary_track=ProgramTrack.LITERACY,
    )
    fixtures.set_clock(FIRST_ORIENTATION_INSTANT)

    oriented = validate_success(
        api_client.complete_orientation(student["id"], headers=make_registrar_headers())
    )
    assert oriented["intake_status"] == IntakeStatus.ORIENTED
    assert oriented["orientation_completed_at"] == FIRST_ORIENTATION_INSTANT
    assert oriented["version"] == student["version"] + 1
    assert oriented["placement_efl_level"] is None
    assert oriented["active_enrollment_count"] == 0


def test_02_a_second_orientation_never_restamps_the_first_instant():
    """"Attempting it on a learner who is not in `INTAKE_STARTED` — including one already
    `ORIENTED` — is refused with `ERR_INVALID_INTAKE_STATE`."

    Design: Corner/state_machines/student_orientation_completion_repeated_rejected
    """
    student = fixtures.create_student(
        full_name="Quill Adeyemi",
        email="quill.adeyemi@example.org",
        primary_track=ProgramTrack.ESL,
    )
    fixtures.set_clock(FIRST_ORIENTATION_INSTANT)
    validate_success(
        api_client.complete_orientation(student["id"], headers=make_registrar_headers())
    )
    fixtures.set_clock(LATER_CLOCK)

    repeat = api_client.complete_orientation(
        student["id"], headers=make_program_coordinator_headers()
    )
    validate_error(repeat, ApiErrorId.INVALID_INTAKE_STATE, expected_status=409)

    stored = fixtures.read_student(student["id"])
    assert stored["intake_status"] == IntakeStatus.ORIENTED
    assert stored["orientation_completed_at"] == FIRST_ORIENTATION_INSTANT


def test_03_a_planned_section_cannot_skip_straight_into_session():
    """"A `PLANNED` section may become `OPEN`; an `OPEN` section may become `IN_SESSION`; and a
    section that is either `OPEN` or `IN_SESSION` may become `CLOSED`, which is terminal. Any
    other combination — reopening a closed section, jumping from `PLANNED` straight to
    `IN_SESSION` or to `CLOSED` — is refused with `ERR_SECTION_TRANSITION_NOT_ALLOWED`."

    Design: Corner/state_machines/class_section_planned_to_in_session_rejected
    """
    section = fixtures.create_section(
        status=SectionStatus.PLANNED,
        program_track=ProgramTrack.HSE_PREP,
        title="Skip A Step",
        instructor_user_id="instructor-5",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
    )

    response = _transition(section["id"], SectionStatus.IN_SESSION)
    validate_error(response, ApiErrorId.SECTION_TRANSITION_NOT_ALLOWED, expected_status=409)

    assert fixtures.read_class_section(section["id"])["status"] == SectionStatus.PLANNED


def test_04_a_closed_section_can_never_resume_intake():
    """"a section that is either `OPEN` or `IN_SESSION` may become `CLOSED`, which is
    terminal. Any other combination — reopening a closed section, jumping from `PLANNED`
    straight to `IN_SESSION` or to `CLOSED` — is refused with
    `ERR_SECTION_TRANSITION_NOT_ALLOWED`."

    Design: Corner/state_machines/class_section_transition_after_closed_rejected
    """
    section = fixtures.create_section(
        status=SectionStatus.PLANNED,
        program_track=ProgramTrack.LITERACY,
        title="Closed For Good",
        instructor_user_id="instructor-6",
        min_efl_level=1,
        max_efl_level=3,
        seats_total=8,
        weekly_hours=4.00,
    )
    fixtures.transition_section(section["id"], SectionStatus.OPEN)
    fixtures.transition_section(section["id"], SectionStatus.CLOSED)

    reopen = _transition(section["id"], SectionStatus.OPEN)
    validate_error(reopen, ApiErrorId.SECTION_TRANSITION_NOT_ALLOWED, expected_status=409)

    reclose = _transition(section["id"], SectionStatus.CLOSED)
    validate_error(reclose, ApiErrorId.SECTION_TRANSITION_NOT_ALLOWED, expected_status=409)

    stored = fixtures.read_class_section(section["id"])
    assert stored["status"] == SectionStatus.CLOSED
    assert stored["seats_taken"] == 0
    assert stored["seats_available"] == 8


def test_05_closing_one_section_settles_two_enrollments_on_two_different_branches():
    """"**Link 1** walks that section's enrollments whose `status` is `ACTIVE`, in `created_at`
    ascending order, and decides each one's fate from its own hour total: an enrollment whose
    `posted_hours` has reached at least forty hours becomes `COMPLETED`, while one below that
    threshold becomes `WITHDRAWN`. Both outcomes record `exit_reason` as `SECTION_CLOSED`, but
    only the `WITHDRAWN` branch stamps `withdrawn_at` with the logical clock's current instant
    — a completed enrollment has no withdrawal instant."

    Design: Corner/state_machines/class_section_close_cascade_completed_and_withdrawn_branches
    """
    context = _setup_two_learners_on_one_section()

    closed = fixtures.transition_section(context["section_id"], SectionStatus.CLOSED)
    assert closed["status"] == SectionStatus.CLOSED
    assert_section_seats_conserved(closed)
    assert closed["seats_taken"] == 0
    assert closed["seats_available"] == 10

    completed = fixtures.read_enrollment(context["full_enrollment_id"])
    assert completed["status"] == EnrollmentStatus.COMPLETED
    assert completed["exit_reason"] == ExitReason.SECTION_CLOSED
    assert completed["withdrawn_at"] is None
    assert_hours_value(completed["posted_hours"], 40.00)
    assert completed["post_test_eligible"] is True

    withdrawn = fixtures.read_enrollment(context["short_enrollment_id"])
    assert withdrawn["status"] == EnrollmentStatus.WITHDRAWN
    assert withdrawn["exit_reason"] == ExitReason.SECTION_CLOSED
    assert withdrawn["withdrawn_at"] == CASCADE_CLOCK
    assert_hours_value(withdrawn["posted_hours"], 8.00)
    assert withdrawn["post_test_eligible"] is False

    full_learner = fixtures.read_student(context["full_student_id"])
    assert full_learner["intake_status"] == IntakeStatus.PLACED
    assert full_learner["active_enrollment_count"] == 0
    assert_hours_value(full_learner["total_instructional_hours"], 40.00)

    short_learner = fixtures.read_student(context["short_student_id"])
    assert short_learner["intake_status"] == IntakeStatus.PLACED
    assert short_learner["active_enrollment_count"] == 0
    assert_hours_value(short_learner["total_instructional_hours"], 8.00)


def test_06_a_seat_released_by_withdrawal_is_not_released_twice():
    """"Withdrawal moves the enrollment from `ACTIVE` to `WITHDRAWN`, stamps `withdrawn_at`
    with the clock's current instant, records the supplied reason, releases the seat by
    decrementing the section's `seats_taken` and recomputing `seats_available`, and decrements
    the learner's `active_enrollment_count`." and "It applies only to an `ACTIVE` enrollment;
    one already `COMPLETED` or `WITHDRAWN` reports `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Corner/state_machines/enrollment_withdraw_repeated_rejected
    """
    context = _setup_active_enrollment(
        "Withdraw Twice", "instructor-9", "Wren Abara", "wren.abara@example.org"
    )
    fixtures.set_clock(WITHDRAW_CLOCK)

    first = validate_success(_withdraw(context["enrollment_id"], WITHDRAW_REASON))
    assert first["status"] == EnrollmentStatus.WITHDRAWN
    assert first["exit_reason"] == WITHDRAW_REASON
    assert first["withdrawn_at"] == WITHDRAW_CLOCK

    repeat = _withdraw(context["enrollment_id"], WITHDRAW_REASON)
    validate_error(repeat, ApiErrorId.ENROLLMENT_NOT_ACTIVE, expected_status=409)

    section = fixtures.read_class_section(context["section_id"])
    assert_section_seats_conserved(section)
    assert section["seats_taken"] == 0
    assert section["seats_available"] == 10

    learner = fixtures.read_student(context["student_id"])
    assert learner["intake_status"] == IntakeStatus.PLACED
    assert learner["active_enrollment_count"] == 0


def test_07_a_withdrawn_enrollment_has_a_frozen_hour_ledger():
    """"Hours may only be posted against an `ACTIVE` enrollment; a completed or withdrawn one
    reports `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Corner/state_machines/attendance_posting_on_withdrawn_enrollment_rejected
    """
    context = _setup_active_enrollment(
        "Frozen Ledger", "instructor-10", "Xan Petrov", "xan.petrov@example.org"
    )
    fixtures.set_clock(WITHDRAW_CLOCK)
    fixtures.post_attendance(context["enrollment_id"], "2026-08-04", 2.00)
    validate_success(_withdraw(context["enrollment_id"], FROZEN_LEDGER_REASON))

    response = api_client.create_attendance_entry(
        context["enrollment_id"],
        factories.create_attendance_entry_payload("2026-08-05", 2.00),
        headers=make_program_coordinator_headers(),
    )
    validate_error(response, ApiErrorId.ENROLLMENT_NOT_ACTIVE, expected_status=409)

    assert_hours_value(fixtures.read_enrollment(context["enrollment_id"])["posted_hours"], 2.00)
    assert_hours_value(
        fixtures.read_student(context["student_id"])["total_instructional_hours"], 2.00
    )


def test_08_a_scored_event_cannot_be_rescored_into_a_new_placement():
    """"Scoring moves the event from `SCHEDULED` to `SCORED`; an event already `SCORED` or
    `INVALIDATED` refuses the attempt with `ERR_TEST_EVENT_NOT_SCHEDULED`."

    Design: Corner/state_machines/test_event_score_repeated_rejected
    """
    placed = fixtures.create_placed_student(
        scale_score=205,
        full_name="Yara Nunez",
        email="yara.nunez@example.org",
        pre_test_at=PRE_TEST_AT,
    )
    fixtures.set_clock(RESCORE_CLOCK)

    response = api_client.score_test_event(
        placed["pre_test"]["id"],
        factories.score_test_event_payload(246),
        headers=make_instructor_headers(),
    )
    validate_error(response, ApiErrorId.TEST_EVENT_NOT_SCHEDULED, expected_status=409)

    event = fixtures.read_test_event(placed["pre_test"]["id"])
    assert event["scale_score"] == 205
    assert event["efl_level"] == 2
    assert event["test_date"] == PRE_TEST_AT

    learner = fixtures.read_student(placed["student_id"])
    assert learner["placement_efl_level"] == 2
    assert learner["intake_status"] == IntakeStatus.PLACED


def test_09_booking_a_test_event_writes_no_placement_yet():
    """"A new event is stored with `status` `SCHEDULED`, `test_date` null, `scale_score` null,
    `efl_level` null and `invalidation_reason` null."

    Design: Corner/state_machines/test_event_initial_state_is_scheduled
    """
    student = fixtures.create_oriented_student(
        full_name="Zora Klein", email="zora.klein@example.org", primary_track=ProgramTrack.ESL
    )

    booked = validate_success(
        api_client.create_test_event(
            factories.create_test_event_payload(
                student["id"],
                BOOKED_FOR,
                purpose=TestEventPurpose.PRE_TEST,
                test_form=TestForm.BEST_PLUS,
            ),
            headers=make_registrar_headers(),
        ),
        expected_status=201,
    )
    assert booked["status"] == TestEventStatus.SCHEDULED
    assert booked["test_date"] is None
    assert booked["efl_level"] is None
    assert booked["scale_score"] is None
    assert booked["scheduled_for"] == BOOKED_FOR
    assert booked["enrollment_id"] is None
    assert booked["invalidation_reason"] is None

    learner = fixtures.read_student(student["id"])
    assert learner["intake_status"] == IntakeStatus.ORIENTED
    assert learner["placement_efl_level"] is None
