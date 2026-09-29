"""Which refusal wins when a request is wrong on several counts, and the capacity gates that
sit at the very bottom of the ladder once every earlier question has been answered.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
)
from test_helpers.types import (
    CenterDecision,
    EnrollmentStatus,
    IntakeStatus,
    ProgramTrack,
    SectionStatus,
    Subtest,
    TestEventPurpose,
    TestEventStatus,
    TestForm,
)

UNKNOWN_ENROLLMENT_ID = "00000000-0000-4000-8000-0000000000ff"
UNKNOWN_CENTER_ID = "00000000-0000-4000-8000-0000000000aa"
OFF_INCREMENT_HOURS = 3.33
UNKNOWN_PATH_ATTENDANCE_DATE = "2026-08-01"

USABLE_EXPIRY = "2027-01-01T00:00:00Z"
PRE_TEST_AT = "2026-08-02T09:00:00Z"
SECOND_PRE_TEST_AT = "2026-08-03T09:00:00Z"
SITTING = ("2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z")

WITHDRAW_REASON = "schedule change"


def _placed_learner(full_name, email, primary_track, scale_score=205, **overrides):
    return fixtures.create_placed_student(
        scale_score=scale_score,
        test_form=TestForm.CASAS_R_900,
        pre_test_at=PRE_TEST_AT,
        full_name=full_name,
        email=email,
        primary_track=primary_track,
        **overrides,
    )


def _register(student_id, session_id, expected_exam_session_version):
    return api_client.create_exam_registration(
        factories.create_exam_registration_payload(
            student_id, session_id, expected_exam_session_version
        ),
        headers=make_registrar_headers(),
    )


def _enroll(student_id, section_id):
    return api_client.create_enrollment(
        factories.create_enrollment_payload(student_id, section_id),
        headers=make_program_coordinator_headers(),
    )


def _open_section(title, program_track, instructor_user_id, **overrides):
    return fixtures.create_section(
        status=SectionStatus.OPEN,
        program_track=program_track,
        title=title,
        instructor_user_id=instructor_user_id,
        **overrides,
    )


def _setup_venue_with_scheduled_math_sitting(
    name, state_code, room_code, proctor_name, requested_seats=5
):
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name=name, state_code=state_code
    )
    room = fixtures.create_room(center["id"], room_code=room_code, seat_capacity=12)
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name=proctor_name,
        daily_hour_cap=8.00,
    )
    session = fixtures.create_session(
        center["id"],
        room["id"],
        SITTING[0],
        SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=requested_seats,
    )
    scheduled = fixtures.assign_session_proctor(center["id"], session["id"], proctor["id"])
    return {"center_id": center["id"], "session_id": session["id"], "session": scheduled}


def test_01_a_missing_path_record_answers_before_the_body_is_inspected():
    """"**Path identifier resolution.** Every identifier embedded in the path is resolved left
    to right, and the first one that does not resolve determines the 404 reported" and "**Request
    shape.** Required body fields present, types correct, enum values drawn from the declared
    set, and numeric constraints satisfied — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/attendance_post_on_unknown_enrollment_with_bad_hours_returns_not_found
    """
    response = api_client.create_attendance_entry(
        UNKNOWN_ENROLLMENT_ID,
        factories.create_attendance_entry_payload(
            UNKNOWN_PATH_ATTENDANCE_DATE, OFF_INCREMENT_HOURS
        ),
        headers=make_instructor_headers(),
    )
    validate_error(response, ApiErrorId.ENROLLMENT_NOT_FOUND, expected_status=404)
    assert response.json()["data"]["error_id"] != ApiErrorId.INVALID_REQUEST


def test_02_an_out_of_role_caller_is_told_so_before_the_centre_is_looked_up():
    """"**Role authorisation.** The acting role appears in the addressed endpoint's role list —
    otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint." and "This ordering is part
    of the contract: an implementation that surfaces a later error instead of an earlier one is
    wrong even though it also refused the request."

    Design: Corner/validations/role_check_precedes_path_existence_unauthorized
    """
    response = api_client.create_testing_room(
        UNKNOWN_CENTER_ID,
        factories.create_testing_room_payload(room_code="R-X", seat_capacity=10),
        headers=make_instructor_headers(),
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED, expected_status=403)
    assert response.json()["data"]["error_id"] != ApiErrorId.TESTING_CENTER_NOT_FOUND


def test_03_a_stale_view_is_reported_before_the_duplicate_seat_it_hides():
    """"**Stale-view guard.** The optimistic-concurrency field matches the parent record's
    current `version` (§2.7) — otherwise the corresponding 412." and "Note the position of this
    band: on those three operations the stale-view guard reports ahead of every state and
    business check that follows, so a client working from a stale read learns that first."

    Design: Corner/validations/stale_session_version_precedes_duplicate_registration
    """
    venue = _setup_venue_with_scheduled_math_sitting(
        "OCC Before Duplicate Center", "WI", "R-1401", "Aya Nordin"
    )
    original_version = venue["session"]["version"]
    placed = _placed_learner(
        "Bram Estes",
        "bram.estes@example.org",
        ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )
    validate_success(
        _register(placed["student_id"], venue["session_id"], original_version),
        expected_status=201,
    )

    replay = _register(placed["student_id"], venue["session_id"], original_version)
    validate_error(replay, ApiErrorId.STALE_EXAM_SESSION_VERSION, expected_status=412)

    session = fixtures.read_session(venue["session_id"])
    assert session["version"] == original_version + 1
    assert session["seats_taken"] == 1

    retry = _register(placed["student_id"], venue["session_id"], session["version"])
    validate_error(retry, ApiErrorId.DUPLICATE_REGISTRATION, expected_status=409)

    assert fixtures.read_session(venue["session_id"])["seats_taken"] == 1


def test_04_the_same_track_twice_is_refused_until_the_first_seat_is_released():
    """"Second, the learner must not already hold an `ACTIVE` enrollment on any section teaching
    the same `program_track`, which `ERR_DUPLICATE_ACTIVE_ENROLLMENT` reports — a learner may
    study two different tracks concurrently, but not the same track twice."

    Design: Corner/validations/duplicate_active_enrollment_in_the_same_track_rejected
    """
    placed = _placed_learner("Cleo Nakhle", "cleo.nakhle@example.org", ProgramTrack.HSE_PREP)
    morning = _open_section(
        "Morning Cohort",
        ProgramTrack.HSE_PREP,
        "instructor-14",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
    )
    evening = _open_section(
        "Evening Cohort",
        ProgramTrack.HSE_PREP,
        "instructor-15",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
    )
    first = fixtures.enroll(placed["student_id"], morning["id"])

    clash = _enroll(placed["student_id"], evening["id"])
    validate_error(clash, ApiErrorId.DUPLICATE_ACTIVE_ENROLLMENT, expected_status=409)
    assert fixtures.read_class_section(evening["id"])["seats_taken"] == 0

    validate_success(
        api_client.withdraw_enrollment(
            first["id"],
            factories.withdraw_enrollment_payload(WITHDRAW_REASON),
            headers=make_program_coordinator_headers(),
        )
    )

    second = validate_success(
        _enroll(placed["student_id"], evening["id"]), expected_status=201
    )
    assert second["status"] == EnrollmentStatus.ACTIVE
    assert second["entry_efl_level"] == 2

    learner = fixtures.read_student(placed["student_id"])
    assert learner["active_enrollment_count"] == 1
    assert learner["intake_status"] == IntakeStatus.ENROLLED


def test_05_a_single_level_band_still_admits_the_learner_standing_on_it():
    """"Third, the learner's `placement_efl_level` must fall inside the section's band, at or
    above `min_efl_level` and at or below `max_efl_level`; a learner outside that band is refused
    with `ERR_EFL_LEVEL_OUT_OF_RANGE`."

    Design: Corner/validations/efl_level_range_is_inclusive_on_both_bounds
    """
    placed = _placed_learner(
        "Dov Renard", "dov.renard@example.org", ProgramTrack.LITERACY, scale_score=221
    )
    assert fixtures.read_student(placed["student_id"])["placement_efl_level"] == 4

    too_high = _open_section(
        "Advanced ESL",
        ProgramTrack.ESL,
        "instructor-16",
        min_efl_level=5,
        max_efl_level=6,
        seats_total=10,
        weekly_hours=6.00,
    )
    exactly_four = _open_section(
        "Level Four Only",
        ProgramTrack.LITERACY,
        "instructor-17",
        min_efl_level=4,
        max_efl_level=4,
        seats_total=10,
        weekly_hours=6.00,
    )

    refused = _enroll(placed["student_id"], too_high["id"])
    validate_error(refused, ApiErrorId.EFL_LEVEL_OUT_OF_RANGE, expected_status=409)

    accepted = validate_success(
        _enroll(placed["student_id"], exactly_four["id"]), expected_status=201
    )
    assert accepted["status"] == EnrollmentStatus.ACTIVE
    assert accepted["entry_efl_level"] == 4

    assert fixtures.read_class_section(too_high["id"])["seats_taken"] == 0
    assert fixtures.read_class_section(exactly_four["id"])["seats_taken"] == 1


def test_06_a_second_pre_test_waits_for_the_first_to_be_scored():
    """"a learner may hold only one `SCHEDULED` test event per `purpose` at a time — a second
    concurrent one of the same purpose is refused with `ERR_TEST_EVENT_CONFLICT`."

    Design: Corner/validations/second_scheduled_pre_test_conflicts_until_the_first_is_scored
    """
    student = fixtures.create_oriented_student(
        full_name="Enid Palacios",
        email="enid.palacios@example.org",
        primary_track=ProgramTrack.HSE_PREP,
    )
    first = fixtures.schedule_test_event(
        student["id"],
        PRE_TEST_AT,
        purpose=TestEventPurpose.PRE_TEST,
        test_form=TestForm.CASAS_R_900,
    )

    def _book_second():
        return api_client.create_test_event(
            factories.create_test_event_payload(
                student["id"],
                SECOND_PRE_TEST_AT,
                purpose=TestEventPurpose.PRE_TEST,
                test_form=TestForm.CASAS_M_900,
            ),
            headers=make_registrar_headers(),
        )

    validate_error(_book_second(), ApiErrorId.TEST_EVENT_CONFLICT, expected_status=409)

    fixtures.set_clock(PRE_TEST_AT)
    fixtures.score_test_event(first["id"], 205)

    second = validate_success(_book_second(), expected_status=201)
    assert second["status"] == TestEventStatus.SCHEDULED
    assert second["test_form"] == TestForm.CASAS_M_900

    page, meta = validate_paginated(
        api_client.list_test_events(
            headers=make_registrar_headers(),
            params={"student_id": student["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 2
    statuses = {row["id"]: row["status"] for row in page}
    assert statuses[first["id"]] == TestEventStatus.SCORED
    assert statuses[second["id"]] == TestEventStatus.SCHEDULED


def test_07_a_one_seat_section_admits_exactly_one_learner():
    """"Fourth, the section must have a free seat: when `seats_taken` already equals
    `seats_total`, the request is refused with `ERR_SECTION_CAPACITY_EXCEEDED`."

    Design: Corner/validations/section_capacity_exceeded_when_last_seat_is_taken
    """
    first = _placed_learner("Fara Iqbal", "fara.iqbal@example.org", ProgramTrack.LITERACY)
    second = _placed_learner("Gene Ostrom", "gene.ostrom@example.org", ProgramTrack.LITERACY)
    section = _open_section(
        "Single Seat",
        ProgramTrack.LITERACY,
        "instructor-18",
        min_efl_level=1,
        max_efl_level=6,
        seats_total=1,
        weekly_hours=4.00,
    )
    fixtures.enroll(first["student_id"], section["id"])

    refused = _enroll(second["student_id"], section["id"])
    validate_error(refused, ApiErrorId.SECTION_CAPACITY_EXCEEDED, expected_status=409)

    stored = fixtures.read_class_section(section["id"])
    assert stored["seats_taken"] == 1
    assert stored["seats_available"] == 0

    learner = fixtures.read_student(second["student_id"])
    assert learner["intake_status"] == IntakeStatus.PLACED
    assert learner["active_enrollment_count"] == 0


def test_08_a_sitting_sells_only_the_seats_it_asked_for():
    """"Its `seat_capacity` is the smaller of the `requested_seats` asked for and the room's own
    `seat_capacity`, so a centre cannot oversell a room by asking for more seats than it has."
    and "the sitting's `seats_taken` must still be below its `seat_capacity`, or
    `ERR_SESSION_SEATS_EXHAUSTED`"

    Design: Corner/validations/session_seats_exhausted_when_capacity_is_one
    """
    venue = _setup_venue_with_scheduled_math_sitting(
        "One Seat Center", "IL", "R-1501", "Hedy Lascu", requested_seats=1
    )
    first = _placed_learner(
        "Ines Kovac",
        "ines.kovac@example.org",
        ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )
    second = _placed_learner(
        "Jonas Weill",
        "jonas.weill@example.org",
        ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
    )
    fixtures.register_candidate(first["student_id"], venue["session_id"])

    session = fixtures.read_session(venue["session_id"])
    assert session["seat_capacity"] == 1
    assert session["seats_taken"] == 1

    refused = _register(second["student_id"], venue["session_id"], session["version"])
    validate_error(refused, ApiErrorId.SESSION_SEATS_EXHAUSTED, expected_status=409)

    learner = fixtures.read_student(second["student_id"])
    assert learner["exam_fee_owed_cents"] == 0
    assert learner["voucher_spent_cents"] == 0
