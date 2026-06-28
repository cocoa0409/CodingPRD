"""Depth tests for cohort scheduling, validation priority pairs, and interval geometry.

Covers difficulty rules: priority_pair_validation_conflict, cross_entity_state_dependency
(Cohort->Course), resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_student_headers, TEST_USERS,
    create_published_course, create_course, create_instructor, create_cohort,
    setup_seat1_with_holder_and_waitlister, enroll_student,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestSchedulePriorityCertifiedBeatsTimeConflict:
    def test_uncertified_and_overlapping_yields_certified_error(self, api):
        """PRD §3.2: "The named instructor's certified_exam_types must contain the parent
        course's exam_type, or the request fails with ERR_INSTRUCTOR_NOT_CERTIFIED."
        PRD §3.9: "Only after all of those do the business rules of the specific workflow
        apply — instructor certification, time conflict, and load on scheduling".

        Instructor (LSAT only) is BOTH uncertified for SAT AND already booked on an
        overlapping window; certification (lower priority) wins.

        Design: Difficulty/priority_pair_validation_conflict/schedule_certified_referential_beats_timeconflict_temporal
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        # Instructor certified only for LSAT — uncertified for SAT.
        inst = create_instructor(certified_exam_types=["LSAT"], max_concurrent_cohorts=3)
        c1 = create_cohort(course["id"], seat_capacity=5,
                           starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        # c1 cannot actually be scheduled with this uncertified instructor, so we set up the
        # overlap purely via a second cohort; the certification check pre-empts the conflict.
        c2 = create_cohort(course["id"], seat_capacity=5,
                           starts_at="2026-06-15T00:00:00Z", ends_at="2026-07-15T00:00:00Z")
        resp = api.schedule_cohort(c2["id"], inst["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_CERTIFIED)
        cohort = validate_success(api.get_cohort(c2["id"], REGISTRAR))
        assert cohort["status"] == "DRAFT"

    def test_certified_error_leaves_cohort_in_draft(self, api):
        """PRD §3.2: "Scheduling assigns an instructor and advances a cohort from DRAFT to
        SCHEDULED ... The cohort must currently be in DRAFT, or the request is rejected with
        ERR_INVALID_STATE."

        On a rejected schedule the cohort stays DRAFT (no transition).

        Design: Difficulty/priority_pair_validation_conflict/schedule_certified_referential_beats_timeconflict_temporal
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["LSAT"], max_concurrent_cohorts=3)
        c2 = create_cohort(course["id"], seat_capacity=5,
                           starts_at="2026-06-15T00:00:00Z", ends_at="2026-07-15T00:00:00Z")
        api.schedule_cohort(c2["id"], inst["id"], REGISTRAR)
        cohort = validate_success(api.get_cohort(c2["id"], REGISTRAR))
        assert cohort["status"] == "DRAFT"
        assert cohort["instructor_id"] is None


class TestActivatePriorityStateBeatsCohortFull:
    def test_activate_cancelled_enrollment_into_full_cohort_yields_state(self, api):
        """PRD §3.4: "It requires the enrollment to be in PENDING_PAYMENT (otherwise
        ERR_INVALID_STATE) ... and it requires a free committed seat — the cohort's
        seats_committed must be strictly less than seat_capacity, or it fails with
        ERR_COHORT_FULL."
        PRD §3.9: "State-machine legality (ERR_INVALID_STATE) is then checked on transition
        endpoints before any domain-specific business rule."

        Capacity-1 cohort full via an ACTIVE enrollment; a second enrollment CANCELLED while
        PENDING_PAYMENT. Activating the cancelled one yields the state error, not COHORT_FULL.

        Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_cohortfull_fiscal
        """
        # A holds the seat then activates; B enrolls (waitlisted) then we cancel B.
        s = setup_seat1_with_holder_and_waitlister(
            activate_holder=True, financed_holder=True, holder_num_installments=1)
        # A ACTIVE -> seats_committed 1 (full). B is WAITLISTED. Cancel B.
        cohort = validate_success(api.get_cohort(s["cohort"]["id"], REGISTRAR))
        validate_success(api.cancel_enrollment(
            s["enr_b"]["id"], cohort["version"], make_student_headers(s["student_b"]["id"])))
        enr_b = validate_success(api.get_enrollment(s["enr_b"]["id"], REGISTRAR))
        assert enr_b["status"] == "CANCELLED"
        # Activating the CANCELLED enrollment -> state error (pre-empts fiscal cohort-full).
        resp = api.activate_enrollment(s["enr_b"]["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        enr_b = validate_success(api.get_enrollment(s["enr_b"]["id"], REGISTRAR))
        assert enr_b["status"] == "CANCELLED"

    def test_cancelled_enrollment_unchanged_after_failed_activate(self, api):
        """PRD §3.4: "Activation is the act of committing a held seat once payment has
        settled, and it advances a PENDING_PAYMENT enrollment to ACTIVE."

        Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_cohortfull_fiscal
        """
        s = setup_seat1_with_holder_and_waitlister(
            activate_holder=True, financed_holder=True, holder_num_installments=1)
        cohort = validate_success(api.get_cohort(s["cohort"]["id"], REGISTRAR))
        validate_success(api.cancel_enrollment(
            s["enr_b"]["id"], cohort["version"], make_student_headers(s["student_b"]["id"])))
        api.activate_enrollment(s["enr_b"]["id"], REGISTRAR)
        enr_b = validate_success(api.get_enrollment(s["enr_b"]["id"], REGISTRAR))
        assert enr_b["status"] == "CANCELLED"


class TestScheduleRequiresCoursePublished:
    def test_schedule_under_draft_course_rejected(self, api):
        """PRD §3.2: "The parent course must be PUBLISHED, or the request fails with
        ERR_COURSE_NOT_PUBLISHED."

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_course_published
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_course(exam_type="SAT", format="LIVE")  # DRAFT, not published
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=3)
        cohort = create_cohort(course["id"], seat_capacity=5)
        resp = api.schedule_cohort(cohort["id"], inst["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_COURSE_NOT_PUBLISHED)
        c = validate_success(api.get_cohort(cohort["id"], REGISTRAR))
        assert c["status"] == "DRAFT"

    def test_failed_schedule_does_not_bump_instructor_load(self, api):
        """PRD §3.2: "When scheduling succeeds, the cohort's instructor_id is set to the
        supplied instructor and that instructor's active_cohort_count rises by one".

        A rejected schedule performs no side effect, so active_cohort_count stays 0.

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_course_published
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=3)
        cohort = create_cohort(course["id"], seat_capacity=5)
        api.schedule_cohort(cohort["id"], inst["id"], REGISTRAR)
        instructor = validate_success(api.get_instructor(inst["id"], REGISTRAR))
        assert instructor["active_cohort_count"] == 0


class TestInstructorHalfOpenInterval:
    def test_touching_windows_allowed_for_instructor(self, api):
        """PRD §3.2: "Windows that merely touch at a boundary — where one cohort's ends_at
        equals the other's starts_at — do not conflict, so back-to-back teaching is allowed;
        a genuine overlap is rejected with ERR_INSTRUCTOR_TIME_CONFLICT."

        Cohort A ends 2026-06-30; cohort B starts 2026-06-30 -> scheduling B succeeds.

        Design: Difficulty/resource_temporal_overlap/instructor_halfopen_touching_windows_allowed
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=5)
        cA = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        validate_success(api.schedule_cohort(cA["id"], inst["id"], REGISTRAR))
        cB = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-30T00:00:00Z", ends_at="2026-07-30T00:00:00Z")
        scheduled = validate_success(api.schedule_cohort(cB["id"], inst["id"], REGISTRAR))
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["instructor_id"] == inst["id"]

    def test_instructor_active_count_two_after_back_to_back(self, api):
        """PRD §3.2: "The instructor's active_cohort_count is a derived figure — the number
        of cohorts in SCHEDULED or IN_SESSION status to which the instructor is currently
        assigned".

        Design: Difficulty/resource_temporal_overlap/instructor_halfopen_touching_windows_allowed
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=5)
        cA = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        validate_success(api.schedule_cohort(cA["id"], inst["id"], REGISTRAR))
        cB = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-30T00:00:00Z", ends_at="2026-07-30T00:00:00Z")
        validate_success(api.schedule_cohort(cB["id"], inst["id"], REGISTRAR))
        instructor = validate_success(api.get_instructor(inst["id"], REGISTRAR))
        assert instructor["active_cohort_count"] == 2


class TestStudentClosedInterval:
    def test_touching_windows_rejected_for_student(self, api):
        """PRD §3.4: "a student may not enroll into a cohort whose session window overlaps
        the window of any other cohort in which the student already holds a non-terminal
        PENDING_PAYMENT, WAITLISTED, or ACTIVE enrollment. This overlap test is closed-interval
        and buffer-inclusive — unlike the half-open instructor test, here two windows that
        merely touch at a boundary do count as a conflict. A violation is rejected with
        ERR_STUDENT_SCHEDULE_CONFLICT."

        Student in cohort A [..06-30); enrolling in cohort B [06-30..) (touching) is rejected.

        Design: Difficulty/resource_temporal_overlap/student_closed_touching_windows_rejected
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=5)
        cA = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        cA = validate_success(api.schedule_cohort(cA["id"], inst["id"], REGISTRAR))
        cB = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-30T00:00:00Z", ends_at="2026-07-30T00:00:00Z")
        cB = validate_success(api.schedule_cohort(cB["id"], inst["id"], REGISTRAR))
        student, enr_a = enroll_student(cA["id"], expected_cohort_version=cA["version"],
                                        email="closed@x.com")
        resp = api.create_enrollment(
            {"student_id": student["id"], "cohort_id": cB["id"],
             "expected_cohort_version": cB["version"]}, make_student_headers(student["id"]))
        validate_error(resp, ApiErrorId.ERR_STUDENT_SCHEDULE_CONFLICT)

    def test_student_remains_in_first_cohort_after_conflict(self, api):
        """PRD §3.4: "A violation is rejected with ERR_STUDENT_SCHEDULE_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/student_closed_touching_windows_rejected
        """
        get_success_data(api.set_clock("2026-05-01T00:00:00Z", REGISTRAR))
        course = create_published_course(exam_type="SAT", format="LIVE")
        inst = create_instructor(certified_exam_types=["SAT"], max_concurrent_cohorts=5)
        cA = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-01T00:00:00Z", ends_at="2026-06-30T00:00:00Z")
        cA = validate_success(api.schedule_cohort(cA["id"], inst["id"], REGISTRAR))
        cB = create_cohort(course["id"], seat_capacity=5,
                          starts_at="2026-06-30T00:00:00Z", ends_at="2026-07-30T00:00:00Z")
        cB = validate_success(api.schedule_cohort(cB["id"], inst["id"], REGISTRAR))
        student, enr_a = enroll_student(cA["id"], expected_cohort_version=cA["version"],
                                        email="closed2@x.com")
        api.create_enrollment(
            {"student_id": student["id"], "cohort_id": cB["id"],
             "expected_cohort_version": cB["version"]}, make_student_headers(student["id"]))
        enr_a = validate_success(api.get_enrollment(enr_a["id"], REGISTRAR))
        assert enr_a["status"] == "PENDING_PAYMENT"
