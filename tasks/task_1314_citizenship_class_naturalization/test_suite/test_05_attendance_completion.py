"""Attendance event log, midterm floor, and completion thresholds (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_attendance_record,
    assert_same_instant,
    assert_seat_ledger_invariants,
    create_general_volunteer,
    create_program,
    create_screened_applicant,
    create_section,
    enroll,
    get_enrollment,
    get_section,
    make_volunteer_headers,
    record_attendance,
    setup_completed_enrollment,
    setup_section_with_enrollees,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["intake_coordinator_headers"]


class TestAttendanceEventLog:
    def test_attendance_record_immutable_event_shape(self, api):
        """PRD §2.4: "Two resources are exceptions by design. An attendance event and
        a training credit are append-only records: they carry only `id` and
        `created_at`, and both `updated_at` and `version` are absent from them. They
        are never modified after creation, so there is nothing to version."

        Design: Corner/entities/attendance_record_immutable_event_shape
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=2, total_sessions=10)
        applicant, _ = create_screened_applicant()
        enrollment = enroll(applicant["id"], section["id"])

        record = validate_success(
            api.create_attendance_record(
                enrollment["id"], {"session_index": 1, "outcome": "PRESENT"},
                make_volunteer_headers(instructor["id"]),
            ),
            201,
        )
        assert_attendance_record(record)
        assert "version" not in record and "updated_at" not in record
        assert record["enrollment_id"] == enrollment["id"]

    def test_attendance_duplicate_session_index_rejected(self, api):
        """PRD §3.4: "Each event records a `session_index` — from 1 to
        `total_sessions`, unique per enrollment, so a repeat index rejects with
        `ERR_SESSION_ALREADY_RECORDED`"

        Design: Corner/endpoints/attendance_duplicate_session_index_rejected
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=2, total_sessions=10)
        applicant, _ = create_screened_applicant()
        enrollment = enroll(applicant["id"], section["id"])
        record_attendance(enrollment["id"], [(1, "PRESENT")], instructor["id"])

        response = api.create_attendance_record(
            enrollment["id"], {"session_index": 1, "outcome": "ABSENT_EXCUSED"},
            make_volunteer_headers(instructor["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SESSION_ALREADY_RECORDED)
        assert get_enrollment(enrollment["id"])["records_count"] == 1, (
            "the failed insert must not append to the event log"
        )


class TestAttendanceComputation:
    def test_attendance_truncation_integer_basis_points(self, api):
        """PRD §3.4: "each append increments the enrollment's `records_count` and
        recomputes `attendance_bp`: the number of events with outcome `PRESENT` or
        `ABSENT_EXCUSED`, multiplied by ten thousand and divided by the total number
        of recorded events, truncated down to whole basis points — and defined as 0
        while no records exist."

        Design: Corner/calculations/attendance_truncation_integer_basis_points
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=2, total_sessions=10)
        applicant, _ = create_screened_applicant()
        enrollment = enroll(applicant["id"], section["id"])
        # 7 attended (PRESENT + ABSENT_EXCUSED) of 9 records; the midterm reading at
        # 5 records is 4/5 = 8000 bp, safely above the 5000 floor.
        record_attendance(
            enrollment["id"],
            [(1, "PRESENT"), (2, "PRESENT"), (3, "PRESENT"), (4, "ABSENT_EXCUSED"),
             (5, "ABSENT_UNEXCUSED"), (6, "PRESENT"), (7, "PRESENT"),
             (8, "ABSENT_EXCUSED"), (9, "ABSENT_UNEXCUSED")],
            instructor["id"],
        )

        enrollment_after = get_enrollment(enrollment["id"])
        assert enrollment_after["records_count"] == 9
        assert enrollment_after["attendance_bp"] == 7777, (
            "floor(7 * 10000 / 9) truncates to 7777, never rounds to 7778"
        )
        assert enrollment_after["status"] == "ENROLLED"


class TestMidtermRevocationCascade:
    def test_attendance_midterm_revoke_seat_promotion_cascade(self, api):
        """PRD §3.4: "The first time an enrollment's `records_count` reaches that
        point, the system compares `attendance_bp` against
        `attendance_midterm_floor_bp`: strictly below the floor, the enrollment is
        automatically revoked — 4999 basis points revokes where the floor is 5000,
        while exactly 5000 survives."
        PRD §3.4: "Revocation moves the enrollment `ENROLLED` → `REVOKED`, decrements
        `enrolled_count`, and frees the seat for promotion selection."

        Design: Difficulty/transitive_cascade/attendance_midterm_revoke_seat_promotion_cascade
        """
        scenario = setup_section_with_enrollees(
            capacity=2, num_applicants=3, total_sessions=10,
            weekday="WED", start_minute=540, end_minute=600, room_id="R3",
        )
        section = scenario["section"]
        instructor = scenario["instructor"]
        enrollment_a, enrollment_b, enrollment_c = scenario["enrollments"]
        assert enrollment_a["status"] == "ENROLLED"
        assert enrollment_b["status"] == "ENROLLED"
        assert enrollment_c["status"] == "WAITLISTED"

        # Four records: 2 attended of 4 (5000 bp) — the midterm point of a
        # 10-session section is 5, so no check has fired yet.
        record_attendance(
            enrollment_a["id"],
            [(1, "PRESENT"), (2, "ABSENT_UNEXCUSED"), (3, "ABSENT_UNEXCUSED"),
             (4, "PRESENT")],
            instructor["id"],
        )
        interim = get_enrollment(enrollment_a["id"])
        assert interim["records_count"] == 4
        assert interim["status"] == "ENROLLED"

        # The fifth record reaches the midterm point with 2/5 attended = 4000 bp,
        # strictly below the 5000 floor: auto-revoke fires and the freed seat
        # promotes the waitlist head.
        record_attendance(
            enrollment_a["id"], [(5, "ABSENT_UNEXCUSED")], instructor["id"]
        )

        revoked = get_enrollment(enrollment_a["id"])
        assert revoked["records_count"] == 5
        assert revoked["attendance_bp"] == 4000
        assert revoked["status"] == "REVOKED"

        promoted = get_enrollment(enrollment_c["id"])
        assert promoted["status"] == "PENDING_PROMOTION"
        assert_same_instant(promoted["offer_expires_at"], "2026-08-04T00:00:00Z")

        untouched = get_enrollment(enrollment_b["id"])
        assert untouched["status"] == "ENROLLED", (
            "the cascade must not touch the sibling enrollment"
        )

        section_after = get_section(section["id"])
        assert section_after["enrolled_count"] == 1
        assert section_after["waitlisted_count"] == 0
        assert section_after["pending_promotion_count"] == 1
        assert_seat_ledger_invariants(section_after)

    def test_attendance_midterm_floor_exact_boundary_survives(self, api):
        """PRD §3.4: "The midterm point of a section is its `total_sessions` divided
        by two and rounded up to a whole number. The first time an enrollment's
        `records_count` reaches that point, the system compares `attendance_bp`
        against `attendance_midterm_floor_bp`: strictly below the floor, the
        enrollment is automatically revoked — 4999 basis points revokes where the
        floor is 5000, while exactly 5000 survives."
        PRD §3.4: "This check fires exactly once per enrollment, at the moment the
        midterm count is first reached."

        Design: Difficulty/transitive_cascade/attendance_midterm_revoke_seat_promotion_cascade
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        # 4 sessions -> midterm point 2; 1 attended of 2 lands exactly on 5000 bp.
        section = create_section(instructor["id"], capacity=2, total_sessions=4,
                                 weekday="WED", start_minute=540, end_minute=600,
                                 room_id="R3")
        applicant, _ = create_screened_applicant()
        enrollment = enroll(applicant["id"], section["id"])

        record_attendance(
            enrollment["id"],
            [(1, "PRESENT"), (2, "ABSENT_UNEXCUSED")],
            instructor["id"],
        )
        at_midterm = get_enrollment(enrollment["id"])
        assert at_midterm["records_count"] == 2
        assert at_midterm["attendance_bp"] == 5000
        assert at_midterm["status"] == "ENROLLED", (
            "exactly 5000 bp survives the strict-below floor"
        )
        assert get_section(section["id"])["enrolled_count"] == 1

        # The check fires exactly once: later dips below the floor do not revoke.
        record_attendance(
            enrollment["id"], [(3, "ABSENT_UNEXCUSED")], instructor["id"]
        )
        after_dip = get_enrollment(enrollment["id"])
        assert after_dip["attendance_bp"] == 3333
        assert after_dip["status"] == "ENROLLED", (
            "the midterm check must not fire a second time"
        )


class TestCompletionThreshold:
    def test_attendance_exactly_8000bp_completion_boundary(self, api):
        """PRD §3.4: "Two thresholds guard it, in order: the record log must be
        complete — `records_count` equal to `total_sessions`, else
        `ERR_SESSIONS_INCOMPLETE` — and only then is the attendance figure judged,
        requiring `attendance_bp` of at least `attendance_complete_bp`, else
        `ERR_ATTENDANCE_BELOW_THRESHOLD`."

        Design: Difficulty/boundary_precision_check/attendance_exactly_8000bp_completion_boundary
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], title="Sat Class", weekday="SAT",
                                 start_minute=600, end_minute=660, room_id="R9",
                                 capacity=3, total_sessions=10)
        applicant_a, _ = create_screened_applicant()
        enrollment_a = enroll(applicant_a["id"], section["id"])
        applicant_b, _ = create_screened_applicant()
        enrollment_b = enroll(applicant_b["id"], section["id"])

        # A: 8 of 10 attended; midterm reading at 5 records is 3/5 = 6000 (survives).
        record_attendance(
            enrollment_a["id"],
            [(1, "PRESENT"), (2, "ABSENT_UNEXCUSED"), (3, "PRESENT"),
             (4, "ABSENT_UNEXCUSED"), (5, "PRESENT"), (6, "PRESENT"), (7, "PRESENT"),
             (8, "PRESENT"), (9, "PRESENT"), (10, "PRESENT")],
            instructor["id"],
        )
        # B: 7 of 10 attended with the same midterm-safe prefix.
        record_attendance(
            enrollment_b["id"],
            [(1, "PRESENT"), (2, "ABSENT_UNEXCUSED"), (3, "PRESENT"),
             (4, "ABSENT_UNEXCUSED"), (5, "PRESENT"), (6, "PRESENT"), (7, "PRESENT"),
             (8, "PRESENT"), (9, "PRESENT"), (10, "ABSENT_UNEXCUSED")],
            instructor["id"],
        )

        completed = validate_success(
            api.complete_enrollment(enrollment_a["id"], COORD), 200
        )
        assert completed["attendance_bp"] == 8000, "8 of 10 is exactly the threshold"
        assert completed["status"] == "COMPLETED", "the threshold is inclusive"

        enrollment_b_now = get_enrollment(enrollment_b["id"])
        assert enrollment_b_now["attendance_bp"] == 7000
        rejected = api.complete_enrollment(enrollment_b["id"], COORD)
        validate_error(rejected, ApiErrorId.ERR_ATTENDANCE_BELOW_THRESHOLD)
        assert get_enrollment(enrollment_b["id"])["status"] == "ENROLLED", (
            "a failed completion is not a transition"
        )

    def test_attendance_above_boundary_completes_and_is_terminal(self, api):
        """PRD §3.4: "Completion is the manual finish, performed by an
        `IntakeCoordinator` and only on an `ENROLLED` enrollment (`ERR_INVALID_STATE`
        otherwise)."
        PRD §3.4: "Success moves the enrollment to `COMPLETED`, a terminal state
        alongside `WITHDRAWN` and `REVOKED`."

        Design: Difficulty/boundary_precision_check/attendance_exactly_8000bp_completion_boundary
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=2, total_sessions=10,
                                 weekday="SAT", start_minute=600, end_minute=660,
                                 room_id="R9")
        applicant, _ = create_screened_applicant()
        enrollment = enroll(applicant["id"], section["id"])
        # 9 of 10 attended -> 9000 bp, strictly above the threshold.
        record_attendance(
            enrollment["id"],
            [(i + 1, "PRESENT") for i in range(9)] + [(10, "ABSENT_UNEXCUSED")],
            instructor["id"],
        )

        completed = validate_success(
            api.complete_enrollment(enrollment["id"], COORD), 200
        )
        assert completed["attendance_bp"] == 9000
        assert completed["status"] == "COMPLETED"

        second_attempt = api.complete_enrollment(enrollment["id"], COORD)
        validate_error(second_attempt, ApiErrorId.ERR_INVALID_STATE)

    def test_complete_with_sessions_incomplete_rejected(self, api):
        """PRD §2.9: "Session completeness is evaluated before the attendance
        threshold within this tier, so a short record log surfaces as
        `ERR_SESSIONS_INCOMPLETE` rather than being masked by
        `ERR_ATTENDANCE_BELOW_THRESHOLD`"
        PRD §3.4: "Two thresholds guard it, in order: the record log must be complete
        — `records_count` equal to `total_sessions`, else `ERR_SESSIONS_INCOMPLETE` —
        and only then is the attendance figure judged, requiring `attendance_bp` of at
        least `attendance_complete_bp`, else `ERR_ATTENDANCE_BELOW_THRESHOLD`."

        Design: Corner/endpoints/complete_with_sessions_incomplete_rejected
        """
        create_program()
        instructor = create_general_volunteer(full_name="Instructor")
        section = create_section(instructor["id"], capacity=2, total_sessions=10)
        applicant, _ = create_screened_applicant()
        enrollment = enroll(applicant["id"], section["id"])
        # 8 attended of 9 records: 8888 bp is above the attendance threshold, but the
        # log is one record short of the 10-session requirement.
        record_attendance(
            enrollment["id"],
            [(1, "PRESENT"), (2, "PRESENT"), (3, "PRESENT"), (4, "PRESENT"),
             (5, "ABSENT_UNEXCUSED"), (6, "PRESENT"), (7, "PRESENT"), (8, "PRESENT"),
             (9, "PRESENT")],
            instructor["id"],
        )
        assert get_enrollment(enrollment["id"])["attendance_bp"] == 8888

        response = api.complete_enrollment(enrollment["id"], COORD)
        validate_error(response, ApiErrorId.ERR_SESSIONS_INCOMPLETE)
        assert get_enrollment(enrollment["id"])["status"] == "ENROLLED"


class TestWithdrawTerminalLockdown:
    def test_withdraw_completed_enrollment_rejected(self, api):
        """PRD §3.4: "Withdrawal is the voluntary exit: an `ENROLLED` enrollment may
        be withdrawn by the applicant or an `IntakeCoordinator` (`ERR_INVALID_STATE`
        in any other status), decrementing `enrolled_count` and freeing the seat for
        promotion selection."
        PRD §3.4: "`enrolled_count` is the number of `ENROLLED` enrollments in the
        section; `pending_promotion_count` is the number of `PENDING_PROMOTION`
        enrollments, because an outstanding promotion offer holds its seat;
        `seats_open` is `capacity` minus `enrolled_count` minus
        `pending_promotion_count`, evaluated in that order."

        Design: Corner/state_machines/withdraw_completed_enrollment_rejected
        """
        context = setup_completed_enrollment(total_sessions=2)
        enrollment = context["enrollment"]
        section = context["section"]
        assert enrollment["status"] == "COMPLETED"

        response = api.withdraw_enrollment(enrollment["id"], COORD)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        # COMPLETED sits outside the ENROLLED ledger, and the failed withdraw must
        # not have moved anything.
        section_after = get_section(section["id"])
        assert section_after["enrolled_count"] == 0
        assert get_enrollment(enrollment["id"])["status"] == "COMPLETED"
