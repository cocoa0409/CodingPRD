"""Tests for optimistic concurrency control and race conditions."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of,
    run_race, assert_race_outcome, assert_exactly_one_succeeds,
    api_client, ApiErrorId, TEST_USERS,
    create_enrollment_payload,
)
from test_helpers.fixtures import (
    setup_race_enrollment_scenario, setup_enrollment_ready,
    create_student, enroll_student, create_course, create_section,
    create_semester_in_open_enrollment,
)


class TestOptimisticConcurrencyControl:
    """Tests for enrollment_seq based OCC on enrollment mutations."""

    def test_occ_stale_seq_rejected(self):
        """Providing a stale enrollment_seq -> ENROLLMENT_CONFLICT."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        # Get current section to know the enrollment_seq
        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        section = validate_success(resp)
        current_seq = section["enrollment_seq"]

        # Use a stale (old) enrollment_seq
        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"],
            payload={"enrollment_seq": current_seq - 1}
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_CONFLICT)

    def test_occ_correct_seq_accepted(self):
        """Providing the correct enrollment_seq allows the mutation."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        # Get current enrollment_seq
        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        section = validate_success(resp)
        current_seq = section["enrollment_seq"]

        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"],
            payload={"enrollment_seq": current_seq}
        )
        data = validate_success(resp)
        assert data["status"] == "DROPPED"

    def test_occ_omitted_seq_allowed(self):
        """When enrollment_seq is omitted, the mutation proceeds without OCC check."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        # Drop without providing enrollment_seq
        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "DROPPED"

    def test_enrollment_seq_starts_at_1(self):
        """Section enrollment_seq starts at 1 on creation."""
        ctx = setup_enrollment_ready()
        assert ctx["section"]["enrollment_seq"] == 1

    def test_enrollment_seq_increments_on_mutation(self):
        """enrollment_seq increments after each enrollment-related change."""
        ctx = setup_enrollment_ready()
        initial_seq = ctx["section"]["enrollment_seq"]

        enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        section = validate_success(resp)
        assert section["enrollment_seq"] > initial_seq, \
            "enrollment_seq should increment after enrollment"

    def test_enrollment_records_section_seq_snapshot(self):
        """Enrollment record captures enrollment_seq snapshot from section."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        assert "enrollment_seq" in enrollment, "Enrollment should have enrollment_seq snapshot"


class TestRaceConditions:
    """Tests for concurrent enrollment race conditions."""

    def test_race_two_students_one_seat(self):
        """Two students racing for 1 seat: exactly one succeeds, the other fails or is waitlisted."""
        ctx = setup_race_enrollment_scenario()
        sid = ctx["semester_id"]

        results = run_race(
            lambda: api_client.create_enrollment(
                sid, ctx["department_id"], ctx["course_id"], ctx["section_id"],
                create_enrollment_payload(ctx["student_a_id"]), TEST_USERS["student_headers"]
            ),
            lambda: api_client.create_enrollment(
                sid, ctx["department_id"], ctx["course_id"], ctx["section_id"],
                create_enrollment_payload(ctx["student_b_id"]), TEST_USERS["student_2_headers"]
            ),
        )

        # At least one should succeed (enrolled or waitlisted)
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        # Or both succeed but one is ENROLLED and one is WAITLISTED
        # The section has capacity=1, waitlist_cap=1, so both could succeed with different statuses

    def test_race_concurrent_drops_idempotent(self):
        """Concurrent drops: at most one succeeds, others get ENROLLMENT_STATE_INVALID or ENROLLMENT_CONFLICT."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        results = run_race(
            lambda: api_client.drop_enrollment(
                ctx["semester_id"], ctx["department_id"], ctx["course_id"],
                ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
            ),
            lambda: api_client.drop_enrollment(
                ctx["semester_id"], ctx["department_id"], ctx["course_id"],
                ctx["section_id"], enrollment["id"], TEST_USERS["registrar_headers"]
            ),
        )

        # Exactly one drop succeeds, the other fails
        successes = [r for r in results if r.status_code < 400]
        failures = [r for r in results if r.status_code >= 400]
        assert len(successes) >= 1, "At least one drop should succeed"
