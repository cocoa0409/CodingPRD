"""Academic record: student defaults, computed measures, grade posting and
correction, duplicate enrollment, uniqueness (PRD §2.9, §3.2).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_gpa,
    create_course_payload,
    create_enrollment_payload,
    create_student_payload,
    enroll,
    get_enrollment,
    get_student,
    make_course,
    make_student,
    validate_error,
    validate_success,
)


class TestStudentDefaults:
    def test_student_defaults_and_zero_computed(self, api, registrar_headers):
        """PRD §3.2: "Students are likewise created by `RegistrarStaff` with a
        unique `student_number` (duplicates meet the same
        `ERR_UNIQUE_CONSTRAINT_VIOLATION`), a `legal_name` that serves as the
        default source for the diploma name, and an optional `financial_hold`
        flag that defaults to false. A student's `status` begins `ACTIVE` and
        becomes `GRADUATED` upon the first degree conferral."
        PRD §2.9: "When the denominator is zero because the student has no
        GPA-bearing enrollments, the GPA is reported as 0.000."

        Design: Corner/entities/student_defaults_and_zero_computed
        """
        student = validate_success(api.create_student(
            create_student_payload(student_number="S-DEF", legal_name="Dee Fault"),
            registrar_headers), 201)
        assert student["financial_hold"] is False
        assert student["status"] == "ACTIVE"
        assert student["total_earned_credits"] == 0
        assert_gpa(student["institutional_gpa"], 0.000)
        assert_gpa(student["cumulative_gpa"], 0.000)

    def test_computed_total_earned_credits_input_ignored(self, api, registrar_headers):
        """PRD §3.2: "Four derived measures are maintained on every student and
        recomputed after every grade event. `total_earned_credits` sums
        `credits_earned` over all of the student's `COMPLETED` enrollments,
        institutional and transfer alike." A brand-new student has no COMPLETED
        enrollments, so the derived sum is 0 regardless of what the client sent.

        Design: Corner/entities/student_computed_fields_input_ignored
        """
        payload = create_student_payload(student_number="S-IGN", legal_name="Ig Nored")
        payload["total_earned_credits"] = 999
        student = validate_success(api.create_student(payload, registrar_headers), 201)
        assert student["total_earned_credits"] == 0


class TestGpaCalculation:
    def test_single_final_rounding_institutional(self, api, registrar_headers):
        """PRD §2.9: "Grade point averages follow a pinned rounding order. A GPA
        is the sum of `grade_points` over the GPA-bearing input set divided by
        the sum of `credits_attempted` over the same set, computed over the full
        input set and rounded **exactly once at the end** to three decimal places
        using round-half-up."

        (4.00 + 6.00 + 4.00) / 4 credits = 14/4 = 3.500 under the pinned order.

        Design: Difficulty/combinatorial_formula/gpa_single_final_rounding_vs_per_term
        """
        c1 = make_course(course_code="CX1", title="One Credit", credits=1)
        c2 = make_course(course_code="CY2", title="Two Credit", credits=2)
        student = make_student(student_number="S-GPA", legal_name="Gail Paige")
        enroll(student["id"], c1["id"], "2024-FA", grade="A")
        enroll(student["id"], c2["id"], "2024-FA", grade="B")
        enroll(student["id"], c1["id"], "2025-SP", grade="A")

        after = get_student(student["id"])
        assert_gpa(after["institutional_gpa"], 3.500)

    def test_single_final_rounding_cumulative_coincides(self, api, registrar_headers):
        """PRD §2.9: "The tempting alternative — rounding each term's GPA to
        three decimals first and then averaging the terms — is wrong and produces
        different values."
        PRD §3.2: "`cumulative_gpa` spans all GPA-bearing enrollments including
        transfer work". With no transfer enrollments the two bases coincide at
        3.500 (the per-term-average order would yield (3.333 + 4.000) / 2 = 3.667).

        Design: Difficulty/combinatorial_formula/gpa_single_final_rounding_vs_per_term
        """
        c1 = make_course(course_code="CX1", title="One Credit", credits=1)
        c2 = make_course(course_code="CY2", title="Two Credit", credits=2)
        student = make_student(student_number="S-GPA", legal_name="Gail Paige")
        enroll(student["id"], c1["id"], "2024-FA", grade="A")
        enroll(student["id"], c2["id"], "2024-FA", grade="B")
        enroll(student["id"], c1["id"], "2025-SP", grade="A")

        after = get_student(student["id"])
        assert_gpa(after["cumulative_gpa"], 3.500)
        assert not (abs(after["cumulative_gpa"] - 3.667) < 1e-6), (
            "per-term round-then-average order is explicitly wrong per PRD §2.9"
        )


class TestTransferCreditPartition:
    def test_transfer_excluded_from_institutional_measures(self, api, registrar_headers):
        """PRD §3.2: "`total_earned_credits` sums `credits_earned` over all of
        the student's `COMPLETED` enrollments, institutional and transfer alike.
        `institutional_earned_credits` applies the same sum restricted to
        enrollments whose `is_transfer` is false. `institutional_gpa` is the
        credit-weighted GPA over non-transfer GPA-bearing enrollments, while
        `cumulative_gpa` spans all GPA-bearing enrollments including transfer
        work"

        3cr institutional A + 5cr transfer B: totals 8 / 3; GPAs 4.000 /
        (12.00 + 15.00) / 8 = 3.375.

        Design: Corner/calculations/transfer_credit_partition
        """
        c3 = make_course(course_code="TP3", title="T3", credits=3)
        c5 = make_course(course_code="TP5", title="T5", credits=5)
        student = make_student(student_number="S-TP", legal_name="Tee Part")
        enroll(student["id"], c3["id"], "2024-FA", grade="A")
        enroll(student["id"], c5["id"], "2024-FA", grade="B", is_transfer=True)

        after = get_student(student["id"])
        assert after["total_earned_credits"] == 8
        assert after["institutional_earned_credits"] == 3
        assert_gpa(after["institutional_gpa"], 4.000)
        assert_gpa(after["cumulative_gpa"], 3.375)


class TestGradePosting:
    def test_post_grade_on_completed_enrollment_rejected(self, api, registrar_headers):
        """PRD §3.2: "Posting against an enrollment that is not `IN_PROGRESS` is
        rejected with `ERR_ENROLLMENT_INVALID_STATE`, and a grade outside the six
        letters is `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/post_grade_on_completed_enrollment_rejected
        """
        course = make_course(course_code="PG3", title="PG", credits=3)
        student = make_student(student_number="S-PG", legal_name="Peg Grade")
        enrollment = enroll(student["id"], course["id"], "2024-FA", grade="B")
        assert enrollment["status"] == "COMPLETED"

        res = api.post_grade(enrollment["id"], {"grade": "A"}, registrar_headers)
        validate_error(res, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value, expected_status=409)

        after = get_enrollment(enrollment["id"])
        assert after["grade"] == "B"
        assert after["credits_earned"] == 3

    def test_withdrawal_reversal_restores_credit(self, api, registrar_headers):
        """PRD §3.2: "a `W` moves it from `IN_PROGRESS` to `WITHDRAWN`" and "a
        letter grade on a `WITHDRAWN` enrollment reverses the withdrawal back to
        `COMPLETED`, restoring the credits."
        PRD §3.2: "Its `grade_points` are `credits_attempted` multiplied by the
        grade's value for grades `A` through `F`" (3cr x B=3.00 -> 9.00).

        Design: Corner/state_machines/withdrawal_reversal_restores_credit
        """
        course = make_course(course_code="WR3", title="WR", credits=3)
        student = make_student(student_number="S-WR", legal_name="Wren Rev")
        enrollment = enroll(student["id"], course["id"], "2024-FA")

        withdrawn = validate_success(api.post_grade(
            enrollment["id"], {"grade": "W"}, registrar_headers), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["credits_earned"] == 0

        restored = validate_success(api.change_grade(
            enrollment["id"],
            {"new_grade": "B", "reason": "withdrawal entered in error"},
            registrar_headers), 200)
        assert restored["status"] == "COMPLETED"
        assert restored["credits_earned"] == 3
        assert restored["grade_points"] == pytest.approx(9.00, abs=1e-6)


class TestDuplicateEnrollment:
    def test_duplicate_then_reenroll_after_withdrawal(self, api, registrar_headers):
        """PRD §3.2: "A second enrollment for the same student, course, and term
        is rejected with `ERR_DUPLICATE_ENROLLMENT` while a sibling exists in
        `IN_PROGRESS` or `COMPLETED`; a `WITHDRAWN` sibling does not block
        re-enrollment."

        Design: Corner/validations/duplicate_enrollment_then_reenroll_after_withdrawal
        """
        course = make_course(course_code="DU3", title="DU", credits=3)
        student = make_student(student_number="S-DU", legal_name="Drew Plex")
        first = enroll(student["id"], course["id"], "2026-SP")
        assert first["status"] == "IN_PROGRESS"

        res = api.create_enrollment(
            student["id"],
            create_enrollment_payload(course["id"], term="2026-SP"),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value, expected_status=409)

        validate_success(api.post_grade(first["id"], {"grade": "W"}, registrar_headers), 200)

        second = validate_success(api.create_enrollment(
            student["id"],
            create_enrollment_payload(course["id"], term="2026-SP"),
            registrar_headers), 201)
        assert second["status"] == "IN_PROGRESS"
        assert second["id"] != first["id"]


class TestImmediateConsistency:
    def test_create_with_grade_returns_computed_fields_immediately(self, api, registrar_headers):
        """PRD §3.2: "When a grade is supplied at creation the enrollment starts
        directly in `COMPLETED` — the transfer and retroactive-recording path —
        and otherwise it starts `IN_PROGRESS` with a null grade."
        PRD §2.11: "Nothing derived is ever left stale."

        Design: Corner/consistency_model/immediate_consistency_on_create_with_grade
        """
        course = make_course(course_code="IC3", title="IC", credits=3)
        student = make_student(student_number="S-IC", legal_name="Ivy Con")

        created = validate_success(api.create_enrollment(
            student["id"],
            create_enrollment_payload(course["id"], term="2024-FA", grade="B"),
            registrar_headers), 201)
        assert created["status"] == "COMPLETED"
        assert created["credits_earned"] == 3
        assert created["grade_points"] == pytest.approx(9.00, abs=1e-6)

        reread = get_enrollment(created["id"])
        assert reread["status"] == created["status"]
        assert reread["credits_earned"] == created["credits_earned"]
        assert reread["grade_points"] == pytest.approx(created["grade_points"], abs=1e-6)


class TestUniqueConstraints:
    def test_duplicate_student_number_and_course_code_rejected(self, api, registrar_headers):
        """PRD §3.2: "`RegistrarStaff` creates each course with a unique
        `course_code` (for example, CS101), a `title`, and the `credits` the
        course carries; a duplicate course code is rejected with
        `ERR_UNIQUE_CONSTRAINT_VIOLATION`. Students are likewise created by
        `RegistrarStaff` with a unique `student_number` (duplicates meet the same
        `ERR_UNIQUE_CONSTRAINT_VIOLATION`)"

        Design: Corner/errors/unique_constraint_violations
        """
        validate_success(api.create_student(
            create_student_payload(student_number="S-UQ", legal_name="Uno Que"),
            registrar_headers), 201)
        validate_success(api.create_course(
            create_course_payload(course_code="UQ1", title="UQ", credits=3),
            registrar_headers), 201)

        res = api.create_student(
            create_student_payload(student_number="S-UQ", legal_name="Second"),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_UNIQUE_CONSTRAINT_VIOLATION.value, expected_status=409)

        res = api.create_course(
            create_course_payload(course_code="UQ1", title="UQ Again", credits=4),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_UNIQUE_CONSTRAINT_VIOLATION.value, expected_status=409)
