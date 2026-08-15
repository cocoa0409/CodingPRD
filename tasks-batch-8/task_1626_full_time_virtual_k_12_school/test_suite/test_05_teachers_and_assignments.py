"""Teacher registration, certification, caseload, and assignment lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_teacher,
    create_district,
    create_enrolled_student,
    create_student,
    create_teacher,
    create_teacher_assignment_payload,
    get_teacher,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_student,
)

ACADEMIC = TEST_USERS["academic_director_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]


class TestCertificationAndStateOrder:
    def _setup_applied_student_and_out_of_state_teacher(self):
        """CA district; student left in APPLIED (never verified); teacher
        certified only in TX."""
        district = create_district(district_code="D-040", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=10)
        student = create_student(district["id"], legal_name="Jack",
                                 date_of_birth="2012-01-01T00:00:00Z",
                                 grade_level=7)
        teacher = create_teacher(full_name="Ms. Lee",
                                 certification_state_codes=["TX"],
                                 caseload_cap=30)
        return student, teacher

    def test_state_check_fires_before_certification(self, api):
        """PRD §3.6: "The checks run in a fixed order. The referenced teacher
        and student must exist (`ERR_NOT_FOUND`). The student must be
        `ENROLLED` (`ERR_INVALID_STATE`). Interstate certification comes next:
        the `state_code` of the student's district of residence must appear
        among the teacher's `certification_state_codes`, or the request fails
        with `ERR_TEACHER_NOT_CERTIFIED_IN_STATE`"
        PRD §2.7: "Every request is validated against an ordered cascade, and
        the first failing check determines the response — later checks are not
        evaluated once an earlier one has failed."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_teacher_assignment
        """
        student, teacher = self._setup_applied_student_and_out_of_state_teacher()
        resp = api.create_teacher_assignment(
            create_teacher_assignment_payload(teacher["id"], student["id"],
                                              subject="ELA"),
            ACADEMIC,
        )
        # Both the state gate and the certification rule are violated; the
        # state gate is evaluated first.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_assignment_leaves_teacher_caseload_unchanged(self, api):
        """PRD §3.6: "The student must be `ENROLLED` (`ERR_INVALID_STATE`)."
        PRD §3.6: "The teacher's `current_caseload` is never written directly:
        it is the count of that teacher's assignments currently in `ASSIGNED`
        status."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_teacher_assignment
        """
        student, teacher = self._setup_applied_student_and_out_of_state_teacher()
        validate_error(
            api.create_teacher_assignment(
                create_teacher_assignment_payload(teacher["id"], student["id"],
                                                  subject="ELA"),
                ACADEMIC),
            ApiErrorId.ERR_INVALID_STATE,
        )
        teacher = get_teacher(teacher["id"])
        assert teacher["current_caseload"] == 0
        _, meta = validate_paginated(
            api.list_student_teacher_assignments(student["id"], ACADEMIC))
        assert meta["total_count"] == 0


class TestTeacherCertification:
    def test_teacher_not_certified_in_student_state_rejected(self, api):
        """PRD §3.6: "Interstate certification comes next: the `state_code` of
        the student's district of residence must appear among the teacher's
        `certification_state_codes`, or the request fails with
        `ERR_TEACHER_NOT_CERTIFIED_IN_STATE`"

        Design: Corner/validations/teacher_not_certified_in_student_state_rejected
        """
        district = create_district(district_code="D-133", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        _, student = create_enrolled_student(district=district,
                                             legal_name="Z3")
        teacher = create_teacher(full_name="OutState",
                                 certification_state_codes=["TX"],
                                 caseload_cap=30)
        resp = api.create_teacher_assignment(
            create_teacher_assignment_payload(teacher["id"], student["id"],
                                              subject="ELA"),
            ACADEMIC,
        )
        validate_error(resp, ApiErrorId.ERR_TEACHER_NOT_CERTIFIED_IN_STATE)


class TestCaseloadAggregateCapacity:
    def _setup_teacher_at_cap(self):
        """Teacher (cap 2, certified CA) with two enrolled CA students already
        ASSIGNED; a third enrolled student awaits assignment."""
        district = create_district(district_code="D-071", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=10)
        teacher = create_teacher(full_name="Ms. Chen",
                                 certification_state_codes=["CA"],
                                 caseload_cap=2)
        _, s1 = create_enrolled_student(district=district, legal_name="Tina")
        assign_teacher(teacher["id"], s1["id"], subject="MATH")
        _, s2 = create_enrolled_student(district=district, legal_name="Uma")
        assign_teacher(teacher["id"], s2["id"], subject="ELA")
        _, s3 = create_enrolled_student(district=district, legal_name="Vic")
        teacher = get_teacher(teacher["id"])
        assert teacher["current_caseload"] == 2
        return teacher, s1, s3

    def test_assignment_beyond_cap_rejected(self, api):
        """PRD §3.6: "Capacity is the final gate: the teacher's
        `current_caseload` plus the proposed assignment must not exceed the
        `caseload_cap`, so filling the cap exactly is allowed while one
        assignment beyond it is rejected with `ERR_CASELOAD_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/teacher_caseload_as_aggregate_capacity
        """
        teacher, _, s3 = self._setup_teacher_at_cap()
        resp = api.create_teacher_assignment(
            create_teacher_assignment_payload(teacher["id"], s3["id"],
                                              subject="SCIENCE"),
            ACADEMIC,
        )
        validate_error(resp, ApiErrorId.ERR_CASELOAD_EXCEEDED)
        assert get_teacher(teacher["id"])["current_caseload"] == 2

    def test_ending_assignment_frees_caseload_for_next_student(self, api):
        """PRD §3.6: "Ending an assignment, again an `AcademicDirector`
        action, moves it from `ASSIGNED` to `ENDED` — the terminal assignment
        state — stamping `ended_at` from the clock, dropping the teacher's
        `current_caseload` by one, and incrementing the assignment's
        `version`."
        PRD §3.6: "Capacity is the final gate: the teacher's
        `current_caseload` plus the proposed assignment must not exceed the
        `caseload_cap`, so filling the cap exactly is allowed while one
        assignment beyond it is rejected with `ERR_CASELOAD_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/teacher_caseload_as_aggregate_capacity
        """
        teacher, s1, s3 = self._setup_teacher_at_cap()
        assignments, _ = validate_paginated(
            api.list_teacher_assignments(teacher["id"], ACADEMIC))
        first = next(a for a in assignments if a["student_id"] == s1["id"])
        ended = validate_success(api.end_teacher_assignment(first["id"], ACADEMIC),
                                 200)
        assert ended["assignment_status"] == "ENDED"
        assert get_teacher(teacher["id"])["current_caseload"] == 1

        resp = api.create_teacher_assignment(
            create_teacher_assignment_payload(teacher["id"], s3["id"],
                                              subject="SCIENCE"),
            ACADEMIC,
        )
        created = validate_success(resp, 201)
        assert created["assignment_status"] == "ASSIGNED"
        assert get_teacher(teacher["id"])["current_caseload"] == 2


class TestAssignmentLifecycle:
    def test_teacher_assignment_terminal_state_lockdown(self, api):
        """PRD §3.6: "Ending an assignment, again an `AcademicDirector`
        action, moves it from `ASSIGNED` to `ENDED` — the terminal assignment
        state — stamping `ended_at` from the clock, dropping the teacher's
        `current_caseload` by one, and incrementing the assignment's
        `version`."
        PRD §2.7: "The target entity must be in a state that admits the
        requested transition."

        Design: Corner/state_machines/teacher_assignment_terminal_state_lockdown
        """
        district = create_district(district_code="D-113", state_code="CA",
                                   funding_rate_cents=500, enrollment_cap=50)
        _, student = create_enrolled_student(district=district, legal_name="T")
        teacher = create_teacher(full_name="T1",
                                 certification_state_codes=["CA"],
                                 caseload_cap=5)
        assignment = assign_teacher(teacher["id"], student["id"],
                                    subject="MATH")
        validate_success(api.end_teacher_assignment(assignment["id"], ACADEMIC),
                         200)
        resp = api.end_teacher_assignment(assignment["id"], ACADEMIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWithdrawalCaseloadCascade:
    def _setup_assigned_then_withdrawn(self):
        """Enrolled TX student with one MATH assignment from a TX-certified
        teacher (cap 5); student withdrawn on 2026-08-10."""
        district = create_district(district_code="D-031", state_code="TX",
                                   funding_rate_cents=400, enrollment_cap=10)
        _, student = create_enrolled_student(district=district, legal_name="Ivy",
                                             date_of_birth="2011-08-08T00:00:00Z",
                                             grade_level=8)
        teacher = create_teacher(full_name="Mr. Jones",
                                 certification_state_codes=["TX"],
                                 caseload_cap=5)
        assignment = assign_teacher(teacher["id"], student["id"],
                                    subject="MATH")
        assert get_teacher(teacher["id"])["current_caseload"] == 1
        set_clock("2026-08-10T08:00:00Z")
        withdraw_student(student["id"], "HOMESCHOOL")
        return teacher, assignment

    def test_withdrawal_ends_teacher_assignment(self, api):
        """PRD §3.3: "Every teacher assignment still `ASSIGNED` for the
        student ends: its `assignment_status` becomes `ENDED`, its `ended_at`
        is stamped from the clock, and the affected teacher's
        `current_caseload` drops by one."

        Design: Difficulty/transitive_cascade/withdraw_cascade_teacher_assignment_caseload_release
        """
        _, assignment = self._setup_assigned_then_withdrawn()
        assignment = validate_success(
            api.get_teacher_assignment(assignment["id"], ACADEMIC))
        assert assignment["assignment_status"] == "ENDED"
        assert assignment["ended_at"] is not None

    def test_withdrawal_releases_teacher_caseload(self, api):
        """PRD §3.3: "Every teacher assignment still `ASSIGNED` for the
        student ends: its `assignment_status` becomes `ENDED`, its `ended_at`
        is stamped from the clock, and the affected teacher's
        `current_caseload` drops by one."

        Design: Difficulty/transitive_cascade/withdraw_cascade_teacher_assignment_caseload_release
        """
        teacher, _ = self._setup_assigned_then_withdrawn()
        assert get_teacher(teacher["id"])["current_caseload"] == 0, (
            "the ended assignment no longer counts against the caseload cap")
