"""Concurrency and OCC tests pinned by explicit PRD prose.

Race tests are generated only when the PRD explicitly names the expected
outcome (PRD §3.7 for refund approve/reject, §3.8 for grading). Tests use
assert_exactly_one_succeeds / assert_race_outcome — never a specific loser
error_id unless the PRD explicitly pins it.
"""

import pytest

from test_helpers import (
    api_client,
    approve_refund_request,
    assert_exactly_one_succeeds,
    create_published_course,
    enroll_student,
    file_refund_request,
    make_student_headers,
    reject_refund_request_payload,
    run_race,
    setup_submission_under_review,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    grade_submission_payload,
    make_instructor_headers,
)


class TestRefundApproveRejectRace:
    """PRD §3.7: 'Concurrent approve and reject calls on the same PENDING
    request serialise on RefundRequest.status: exactly one transition wins;
    the other sees ERR_REFUND_NOT_PENDING.'"""

    def test_concurrent_approve_and_reject_exactly_one_wins(self, api):
        """PRD §3.7: 'Concurrent approve and reject calls on the same PENDING
        request serialise on RefundRequest.status: exactly one transition
        wins; the other sees ERR_REFUND_NOT_PENDING.'"""
        course, _, _ = create_published_course()
        enrollment, student = enroll_student(course)
        refund = file_refund_request(enrollment, student)
        results = run_race(
            lambda: api.approve_refund_request(refund["id"], TEST_USERS["admin_headers"]),
            lambda: api.reject_refund_request(
                refund["id"], reject_refund_request_payload("ineligible"),
                TEST_USERS["admin_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The loser must surface ERR_REFUND_NOT_PENDING per PRD §3.7.
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_REFUND_NOT_PENDING")


class TestSubmissionGradeRace:
    """PRD §3.8: 'Two concurrent grade calls on the same submission serialise
    on the submission's status: the first wins, the second sees
    ERR_SUBMISSION_NOT_UNDER_REVIEW.'"""

    def test_concurrent_grades_first_wins_second_sees_not_under_review(self, api):
        """PRD §3.8: 'Two concurrent grade calls on the same submission
        serialise on the submission's status: the first wins, the second
        sees ERR_SUBMISSION_NOT_UNDER_REVIEW.'"""
        course, instructor, _, _, _, sub = setup_submission_under_review()
        results = run_race(
            lambda: api.grade_submission(
                sub["id"],
                grade_submission_payload(score=80, feedback="ok"),
                make_instructor_headers(instructor["id"]),
            ),
            lambda: api.grade_submission(
                sub["id"],
                grade_submission_payload(score=70, feedback="also ok"),
                make_instructor_headers(instructor["id"]),
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_SUBMISSION_NOT_UNDER_REVIEW")


class TestRefundIdempotencyRace:
    """PRD §3.7: 'The system serialises concurrent refund requests on the
    same enrolment so that at most one non-terminal RefundRequest exists at
    a time; the second-arriving request sees ERR_REFUND_ALREADY_REQUESTED.'"""

    def test_concurrent_refund_requests_one_succeeds(self, api):
        """PRD §3.7: 'The system serialises concurrent refund requests on the
        same enrolment so that at most one non-terminal RefundRequest exists
        at a time; the second-arriving request sees
        ERR_REFUND_ALREADY_REQUESTED.'"""
        from test_helpers import create_refund_request_payload
        course, _, _ = create_published_course()
        enrollment, student = enroll_student(course)
        student_headers = make_student_headers(student["id"])
        results = run_race(
            lambda: api.create_refund_request(
                enrollment["id"], create_refund_request_payload(), student_headers
            ),
            lambda: api.create_refund_request(
                enrollment["id"], create_refund_request_payload(), student_headers
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, "ERR_REFUND_ALREADY_REQUESTED")


class TestOptimisticConcurrency:
    """PRD §2.5: 'Endpoints that modify a resource by its identifier accept an
    optional version value in the request body. When present, the server
    compares it to the current version of the target row and rejects the
    request with ERR_STALE_DATA if they differ.'"""

    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.5: 'When present, the server compares it to the current
        version of the target row and rejects the request with ERR_STALE_DATA
        if they differ.'"""
        from test_helpers import create_draft_course, make_instructor_headers
        course, instructor = create_draft_course(list_price_cents=10000)
        stale_version = course["version"]
        instr_headers = make_instructor_headers(instructor["id"])
        # First patch increments version.
        api.patch_course(
            course["id"], {"list_price_cents": 20000, "version": stale_version},
            instr_headers,
        )
        # Second patch with stale version must fail.
        res = api.patch_course(
            course["id"], {"list_price_cents": 30000, "version": stale_version},
            instr_headers,
        )
        validate_error(res, "ERR_STALE_DATA")
