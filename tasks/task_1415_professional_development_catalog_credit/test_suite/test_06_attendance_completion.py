"""Attendance recording/verification, the survey dimension, and completion gates."""
from test_helpers import (
    NON_EXISTENT_UUID, TEST_USERS, complete_registration,
    make_instructor, make_teacher,
    record_marks, register_teacher, run_ops, set_clock, setup_catalog_scenario,
    setup_completed_course, validate_error, validate_success, validate_paginated,
    verify_registration, waive_registration_survey, make_instructor_headers,
    make_teacher_headers,
)
from test_helpers.factories import create_survey_payload
from test_helpers.constants import CLOCK_IN_SESSION


class TestAttendanceEightyPercentBoundary:
    FIVE_MEETINGS = [
        ("2026-08-15T10:00:00Z", "2026-08-15T11:00:00Z", "R1"),
        ("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z", "R1"),
        ("2026-08-15T14:00:00Z", "2026-08-15T15:00:00Z", "R1"),
        ("2026-08-16T10:00:00Z", "2026-08-16T11:00:00Z", "R1"),
        ("2026-08-17T10:00:00Z", "2026-08-17T11:00:00Z", "R1"),
    ]

    def _scenario(self):
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "ATT-10", "clock_hours": 10,
                              "fee_cents": 0},
            meeting_times=self.FIVE_MEETINGS)
        t1 = make_teacher(sc.building["id"], email="tf@x.com", full_name="T F")
        t2 = make_teacher(sc.building["id"], email="tg@x.com", full_name="T G")
        r1 = register_teacher(t1["id"], sc.section["id"])
        r2 = register_teacher(t2["id"], sc.section["id"])
        # r1 attends 4 of 5; r2 attends 3 of 5.
        marks = {
            r1["id"]: ["PRESENT", "PRESENT", "PRESENT", "PRESENT", "ABSENT"],
            r2["id"]: ["PRESENT", "PRESENT", "PRESENT", "ABSENT", "ABSENT"],
        }
        for meeting, idx in zip(sc.meetings, range(5)):
            record_marks(meeting["id"], sc.instructor["id"], [
                {"registration_id": r1["id"], "mark": marks[r1["id"]][idx]},
                {"registration_id": r2["id"], "mark": marks[r2["id"]][idx]},
            ])
        return sc, r1, r2

    def test_four_of_five_passes_inclusive_boundary(self, api):
        """PRD §3.4: "The rate check itself is integer arithmetic only: the
        attended count — marks of `PRESENT` or `EXCUSED`, since an excused
        absence counts as attended — multiplied by five must be at least the
        total meeting count multiplied by four. Four meetings attended of five
        passes; three of five fails. Passing sets `attendance_status` to
        `VERIFIED`; failing sets it to `ABSENT`."

        Design: Difficulty/boundary_precision_check/boundary_attendance_eighty_percent
        """
        sc, r1, _r2 = self._scenario()
        verified = verify_registration(r1["id"], sc.instructor["id"])
        assert verified["attendance_status"] == "VERIFIED", (
            "4 attended of 5: 4*5 == 20 >= 5*4 == 20 — the boundary is inclusive")

    def test_three_of_five_fails(self, api):
        """PRD §3.4: "The rate check itself is integer arithmetic only: the
        attended count — marks of `PRESENT` or `EXCUSED`, since an excused
        absence counts as attended — multiplied by five must be at least the
        total meeting count multiplied by four. Four meetings attended of five
        passes; three of five fails. Passing sets `attendance_status` to
        `VERIFIED`; failing sets it to `ABSENT`."

        Design: Difficulty/boundary_precision_check/boundary_attendance_eighty_percent
        """
        sc, _r1, r2 = self._scenario()
        failed = verify_registration(r2["id"], sc.instructor["id"])
        assert failed["attendance_status"] == "ABSENT", "3 of 5: 15 >= 20 is false"


class TestParallelDimensions:
    def _two_registrants(self):
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "PAR-6", "clock_hours": 6,
                              "fee_cents": 0},
            section_overrides={"seat_capacity": 2})
        t1 = make_teacher(sc.building["id"], email="t6@x.com", full_name="T Six")
        t2 = make_teacher(sc.building["id"], email="t7@x.com", full_name="T Seven")
        r1 = register_teacher(t1["id"], sc.section["id"])
        r2 = register_teacher(t2["id"], sc.section["id"])
        return sc, t1, t2, r1, r2

    def test_survey_submitted_while_attendance_pending(self, api):
        """PRD §3.4: "The teacher — and only the teacher themselves — submits the
        evaluation once, while the registration is `REGISTERED` or `COMPLETED`".
        PRD §3.4: "The survey runs in parallel as the registration's
        `survey_status`."

        Design: Difficulty/non_linear_state_machine/non_linear_registration_parallel_dimensions
        """
        sc, t1, _t2, r1, _r2 = self._two_registrants()
        # T1 submits the survey early: attendance dimension untouched.
        validate_success(api.submit_survey(
            r1["id"], create_survey_payload(overall_rating=4, would_recommend=True),
            make_teacher_headers(t1["id"])), 201)
        after = validate_success(api.get_registration(
            r1["id"], TEST_USERS["coordinator_headers"]), 200)
        assert after["survey_status"] == "SUBMITTED"
        assert after["attendance_status"] == "PENDING", "dimensions are independent"
        assert after["status"] == "REGISTERED"

        # Finish both dimensions and complete.
        record_marks(sc.meetings[0]["id"], sc.instructor["id"],
                     [{"registration_id": r1["id"], "mark": "PRESENT"}])
        verify_registration(r1["id"], sc.instructor["id"])
        set_clock(CLOCK_IN_SESSION)
        run_ops()
        done = complete_registration(r1["id"])
        assert done["status"] == "COMPLETED"

    def test_completion_gated_on_survey_after_attendance(self, api):
        """PRD §3.5: "Completing requires the section to be `IN_SESSION` or
        `COMPLETED`, the registration's `attendance_status` to be `VERIFIED`, and
        its `survey_status` to be `SUBMITTED` or `WAIVED` — the two gates
        surfacing, in that order, as `ERR_ATTENDANCE_NOT_VERIFIED` then
        `ERR_SURVEY_NOT_SUBMITTED` per §2.10."

        Design: Difficulty/non_linear_state_machine/non_linear_registration_parallel_dimensions
        """
        sc, _t1, _t2, _r1, r2 = self._two_registrants()
        record_marks(sc.meetings[0]["id"], sc.instructor["id"],
                     [{"registration_id": r2["id"], "mark": "PRESENT"}])
        verify_registration(r2["id"], sc.instructor["id"])
        set_clock(CLOCK_IN_SESSION)
        run_ops()
        # Attendance VERIFIED but survey still PENDING.
        res = api.complete_registration(r2["id"], TEST_USERS["coordinator_headers"])
        validate_error(res, "ERR_SURVEY_NOT_SUBMITTED", expected_status=400)
        # Waive the survey; completion now succeeds.
        waive_registration_survey(r2["id"])
        done = complete_registration(r2["id"])
        assert done["status"] == "COMPLETED"


def test_verify_attendance_incomplete_records_rejected(api):
    """PRD §3.4: "Every meeting of the section must already hold a record for
    this registration; if any meeting lacks one, the attempt fails with
    `ERR_ATTENDANCE_INCOMPLETE`."

    Design: Corner/validations/verify_attendance_incomplete_records_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "AI-1", "clock_hours": 5, "fee_cents": 0},
        meeting_times=[("2026-08-15T10:00:00Z", "2026-08-15T11:00:00Z", "R1"),
                       ("2026-08-15T12:00:00Z", "2026-08-15T13:00:00Z", "R1")])
    teacher = make_teacher(sc.building["id"], email="tai@x.com")
    registration = register_teacher(teacher["id"], sc.section["id"])
    # Record only the first of the two meetings.
    record_marks(sc.meetings[0]["id"], sc.instructor["id"],
                 [{"registration_id": registration["id"], "mark": "PRESENT"}])
    res = api.verify_attendance(registration["id"],
                                make_instructor_headers(sc.instructor["id"]))
    validate_error(res, "ERR_ATTENDANCE_INCOMPLETE", expected_status=400)


def test_complete_without_attendance_rejected(api):
    """PRD §3.5: "Completing requires the section to be `IN_SESSION` or
    `COMPLETED`, the registration's `attendance_status` to be `VERIFIED`, and its
    `survey_status` to be `SUBMITTED` or `WAIVED` — the two gates surfacing, in
    that order, as `ERR_ATTENDANCE_NOT_VERIFIED` then `ERR_SURVEY_NOT_SUBMITTED`
    per §2.10."

    Design: Corner/validations/complete_without_attendance_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "NA-1", "clock_hours": 5, "fee_cents": 0})
    teacher = make_teacher(sc.building["id"], email="tna@x.com")
    registration = register_teacher(teacher["id"], sc.section["id"])
    waive_registration_survey(registration["id"])  # survey WAIVED, attendance PENDING
    set_clock(CLOCK_IN_SESSION)
    run_ops()
    res = api.complete_registration(registration["id"],
                                    TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_ATTENDANCE_NOT_VERIFIED", expected_status=400)


def test_survey_second_submission_rejected(api):
    """PRD §3.4: "a second survey for the same registration is rejected with
    `ERR_SURVEY_ALREADY_SUBMITTED` (HTTP 409)."

    Design: Corner/validations/survey_second_submission_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "SS-1", "clock_hours": 5, "fee_cents": 0})
    teacher = make_teacher(sc.building["id"], email="tss@x.com")
    registration = register_teacher(teacher["id"], sc.section["id"])
    validate_success(api.submit_survey(
        registration["id"], create_survey_payload(overall_rating=4),
        make_teacher_headers(teacher["id"])), 201)
    res = api.submit_survey(
        registration["id"], create_survey_payload(overall_rating=1,
                                                  would_recommend=False),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_SURVEY_ALREADY_SUBMITTED", expected_status=409)


def test_survey_after_waive_rejected(api):
    """PRD §3.4: "The submission creates the immutable `SurveyResponse` (see
    §2.5 for its reduced field set), stamps its `submitted_at`, moves
    `survey_status` from `PENDING` to `SUBMITTED`" — the transition is defined
    from `PENDING` only, and per PRD §2.10 step 6 a lifecycle violation surfaces
    as `ERR_INVALID_STATE`. PRD §3.4: "a `PDCoordinator` may waive the
    requirement, supplying a `reason`, while the registration is `REGISTERED`,
    moving `survey_status` to `WAIVED`."

    Design: Corner/state_machines/survey_after_waive_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "SV-1", "clock_hours": 5, "fee_cents": 0})
    teacher = make_teacher(sc.building["id"], email="tsv@x.com")
    registration = register_teacher(teacher["id"], sc.section["id"])
    waive_registration_survey(registration["id"], reason="coordinator waiver")
    res = api.submit_survey(
        registration["id"], create_survey_payload(overall_rating=5),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=400)


def test_bulk_attendance_atomic_rejected(api):
    """PRD §3.4: "a payload of `records`, each naming a `registration_id` and a
    `mark` of `PRESENT`, `ABSENT`, or `EXCUSED`, is applied atomically — any
    invalid item rejects the whole request — and upserts the `AttendanceRecord`
    for the (`registration_id`, `meeting_id`) pair". PRD §2.9: "Body-referenced
    foreign keys — `teacher_id`, `section_id`, ... — are validated after path
    identifiers, and a missing referenced resource likewise yields
    `ERR_NOT_FOUND`."

    Design: Corner/endpoints/bulk_attendance_atomic_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "BK-1", "clock_hours": 5, "fee_cents": 0})
    teacher = make_teacher(sc.building["id"], email="tbk@x.com")
    registration = register_teacher(teacher["id"], sc.section["id"])
    meeting_id = sc.meetings[0]["id"]
    res = api.record_attendance(
        meeting_id,
        {"records": [
            {"registration_id": registration["id"], "mark": "PRESENT"},
            {"registration_id": NON_EXISTENT_UUID, "mark": "ABSENT"},
        ]},
        make_instructor_headers(sc.instructor["id"]))
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    data, meta = validate_paginated(
        api.get_meeting_attendance(meeting_id, TEST_USERS["coordinator_headers"]))
    assert data == [] and meta["total_count"] == 0, (
        "atomic bulk: the valid PRESENT row was not persisted")


def test_attendance_by_non_instructor_rejected(api):
    """PRD §2.1: "When `X-User-Role` is `Instructor`, `X-User-ID` is again the
    `id` of an `Employee`; the instructor may only act on sections whose
    `instructor_id` equals that `X-User-ID`, and violations surface as
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/attendance_by_non_instructor_rejected
    """
    sc = setup_catalog_scenario(
        course_overrides={"course_code": "RI-1", "clock_hours": 5, "fee_cents": 0})
    other_instructor = make_instructor(sc.building["id"], email="i2@x.com",
                                       full_name="I Two")
    teacher = make_teacher(sc.building["id"], email="tri@x.com")
    registration = register_teacher(teacher["id"], sc.section["id"])
    res = api.record_attendance(
        sc.meetings[0]["id"],
        {"records": [{"registration_id": registration["id"], "mark": "PRESENT"}]},
        make_instructor_headers(other_instructor["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_drop_completed_registration_rejected(api):
    """PRD §3.3: "A `REGISTERED` teacher may drop (or be dropped by a
    coordinator) while the section is `PUBLISHED` or `REGISTRATION_CLOSED`" — a
    `COMPLETED` registration admits no drop, and per PRD §2.10 step 6 a lifecycle
    violation surfaces as `ERR_INVALID_STATE`. PRD §3.5: "the registration
    becomes `COMPLETED` with `completed_at` set to the logical now".

    Design: Corner/state_machines/drop_completed_registration_rejected
    """
    sc = setup_completed_course(clock_hours=5, fee_cents=0,
                                course_overrides={"course_code": "TL-1"})
    assert sc.registration["status"] == "COMPLETED"
    res = api.drop_registration(sc.registration["id"],
                                make_teacher_headers(sc.teacher["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=400)
