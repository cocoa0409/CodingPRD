"""Authentication, role permission, and ownership tests (PRD §2.1, §2.8)."""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    build_user_headers,
    create_course_payload,
    create_instructor,
    create_instructor_payload,
    create_published_course,
    create_student,
    create_student_payload,
    enroll_student,
    make_instructor_headers,
    make_student_headers,
    validate_error,
    validate_success,
)


class TestMissingOrInvalidUserContextHeader:
    """PRD §2.1: 'Requests that omit either header, or that send a value that is
    empty or otherwise invalid, are rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""

    def test_missing_both_headers(self, api):
        """PRD §2.1: 'Requests that omit either header... are rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        instructor = create_instructor()
        res = api.create_course(
            create_course_payload(instructor["id"]),
            headers={},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_missing_user_id_header(self, api):
        """PRD §2.1: 'Requests that omit either header... are rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        instructor = create_instructor()
        res = api.create_course(
            create_course_payload(instructor["id"]),
            headers={"X-User-Role": "Instructor"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_missing_user_role_header(self, api):
        """PRD §2.1: 'Requests that omit either header... are rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        instructor = create_instructor()
        res = api.create_course(
            create_course_payload(instructor["id"]),
            headers={"X-User-ID": instructor["id"]},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_empty_user_id_value(self, api):
        """PRD §2.1: 'or that send a value that is empty or otherwise invalid, are
        rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        instructor = create_instructor()
        res = api.create_course(
            create_course_payload(instructor["id"]),
            headers={"X-User-ID": "", "X-User-Role": "Instructor"},
        )
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


class TestForbiddenRole:
    """PRD §2.1: 'Requests whose role is syntactically valid but is not authorised
    for the targeted endpoint are rejected with ERR_FORBIDDEN_ROLE.'"""

    def test_student_cannot_create_course(self, api):
        """PRD §2.1: 'Requests whose role is syntactically valid but is not
        authorised for the targeted endpoint are rejected with
        ERR_FORBIDDEN_ROLE.' Course creation is Instructor-only per PRD §4."""
        student = create_student()
        instructor = create_instructor()
        res = api.create_course(
            create_course_payload(instructor["id"]),
            headers=make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_instructor_cannot_delist_course(self, api):
        """PRD §2.1: 'Requests whose role is syntactically valid but is not
        authorised for the targeted endpoint are rejected with
        ERR_FORBIDDEN_ROLE.' PRD §4 reserves POST /courses/{id}/delist to
        AcademicAdmin only."""
        course, instructor, _ = create_published_course()
        res = api.delist_course(course["id"], make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_instructor_cannot_list_audit_logs(self, api):
        """PRD §4: GET /audit-logs is restricted to AcademicAdmin. Per PRD §2.1,
        a non-authorised role is rejected with ERR_FORBIDDEN_ROLE."""
        instructor = create_instructor()
        res = api.list_audit_logs(make_instructor_headers(instructor["id"]))
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_student_cannot_advance_clock(self, api):
        """PRD §3.9: '/_clock/advance' is restricted to AcademicAdmin. Other
        roles fall under PRD §2.1's ERR_FORBIDDEN_ROLE rule."""
        student = create_student()
        res = api.advance_clock(60, make_student_headers(student["id"]))
        validate_error(res, "ERR_FORBIDDEN_ROLE")


class TestForbiddenNotOwner:
    """PRD §2.1: 'Ownership checks on any resource that references an Instructor
    (most importantly a Course, where ownership is recorded in instructor_id...).
    A mismatch surfaces as ERR_FORBIDDEN_NOT_OWNER.'"""

    def test_non_owner_instructor_cannot_submit_course(self, api):
        """PRD §3.1: 'Submitting requires that the caller is the course owner
        (ERR_FORBIDDEN_NOT_OWNER).'"""
        from test_helpers import create_draft_course, add_chapter
        course, owner = create_draft_course()
        add_chapter(course, owner)
        other_instructor = create_instructor()
        res = api.submit_course_for_review(
            course["id"], make_instructor_headers(other_instructor["id"])
        )
        validate_error(res, "ERR_FORBIDDEN_NOT_OWNER")

    def test_non_owner_student_cannot_resubmit(self, api):
        """PRD §3.8: 'the caller must own the underlying enrolment
        (ERR_FORBIDDEN_NOT_OWNER)' for PUT /submissions/{id}/payload."""
        from test_helpers import (
            publish_assignment,
            request_revision,
            start_review,
            submit_assignment,
            update_submission_payload,
        )
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        sub = submit_assignment(assignment, enrollment, student, fmt="TEXT")
        sub = start_review(sub, instructor)
        sub = request_revision(sub, instructor, "redo")
        # Different student attempts the resubmit.
        other_student = create_student()
        res = api.update_submission_payload(
            sub["id"],
            update_submission_payload(fmt="TEXT"),
            make_student_headers(other_student["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN_NOT_OWNER")

    def test_owner_with_correct_id_can_submit(self, api):
        """PRD §2.1 sanity: when X-User-ID == Course.instructor_id, the
        ownership check passes and the request proceeds."""
        from test_helpers import create_draft_course, add_chapter
        course, owner = create_draft_course()
        add_chapter(course, owner)
        res = api.submit_course_for_review(
            course["id"], make_instructor_headers(owner["id"])
        )
        validate_success(res, expected_status=200)
